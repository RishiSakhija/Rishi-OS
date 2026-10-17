"""The one and only model router (AGENTS.md Rule 4).

All model access in Rishi-OS goes through `call_llm`. No agent may POST to a
provider itself, and no agent may hold its own key.

Fallback chain, walked in order until one provider answers:

    Provider A   DeepSeek
    A-fallback   NVIDIA NIM
    Provider B   Google Gemini
    Provider C   Groq
    Local        Ollama        (keyless last resort)

On retries
----------
Rule 5 says "retry once on failure", and Rule 2 says one model call per run.
Those reconcile like this: **a transient provider failure is handled by walking
to the next provider in the chain**, not by hammering the same endpoint. The
chain is therefore the retry mechanism, and it is finite -- the walk is bounded
by the number of configured providers, so no retry loop can exist.

Callers who genuinely want a second attempt against the *same* provider can
pass `retry_same_provider=True`, which adds exactly one extra attempt, for that
provider only. Total attempts remain hard-capped by `max_attempts`.

`call_llm` never raises. On total failure it returns an `LLMResult` with
`status="failed"`, and the caller logs and exits 0 (AGENTS.md Rule 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from . import config, db


@dataclass
class LLMResult:
    """Normalised result of a router call."""

    text: str = ""
    model: str | None = None
    provider: str | None = None
    calls: int = 0
    status: str = config.STATUS_FAILED
    notes: str = ""
    attempts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and bool(self.text)


SYSTEM_DEFAULT = (
    "You are a precise writing assistant for a small startup studio. "
    "Follow the requested output template exactly, using the given markdown "
    "headings. Be concrete and concise. Never invent statistics or quotes. "
    "Return only the requested content -- no preamble, no apologies."
)


def _messages(prompt: str, system: str | None) -> list[dict]:
    return [
        {"role": "system", "content": system or SYSTEM_DEFAULT},
        {"role": "user", "content": prompt},
    ]


def _call_openai(provider: dict, prompt: str, system: str | None,
                 max_tokens: int, temperature: float) -> str:
    """DeepSeek, NVIDIA NIM and Groq all speak the OpenAI chat format."""
    url = provider["base"].rstrip("/") + provider["path"]
    headers = {
        "Authorization": f"Bearer {config.provider_key(provider)}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider["model"],
        "messages": _messages(prompt, system),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    response = requests.post(
        url, headers=headers, json=payload, timeout=config.HTTP_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def _call_gemini(provider: dict, prompt: str, system: str | None,
                 max_tokens: int, temperature: float) -> str:
    url = (
        provider["base"].rstrip("/")
        + provider["path"]
        + f"?key={config.provider_key(provider)}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system or SYSTEM_DEFAULT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    response = requests.post(url, json=payload, timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return (data["candidates"][0]["content"]["parts"][0]["text"] or "").strip()


def _call_ollama(provider: dict, prompt: str, system: str | None,
                 max_tokens: int, temperature: float) -> str:
    url = provider["base"].rstrip("/") + provider["path"]
    payload = {
        "model": provider["model"],
        "messages": _messages(prompt, system),
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    response = requests.post(url, json=payload, timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return (data["message"]["content"] or "").strip()


_HANDLERS = {
    "openai": _call_openai,
    "gemini": _call_gemini,
    "ollama": _call_ollama,
}


def call_llm(
    prompt: str,
    *,
    system: str | None = None,
    agent: str | None = None,
    max_tokens: int = 900,
    temperature: float = 0.4,
    retry_same_provider: bool = False,
) -> LLMResult:
    """Make one (or fallback-chained) model call and return an LLMResult.

    `prompt` is trimmed to `MAX_INPUT_CHARS` before it leaves the process
    (AGENTS.md Rule 3). Never raises.
    """
    prompt, truncated = config.trim(prompt)
    if not prompt.strip():
        return LLMResult(status=config.STATUS_FAILED, notes="empty prompt")

    chain = config.available_providers()
    if not chain:
        return LLMResult(
            status=config.STATUS_FAILED,
            notes="no providers configured (no API keys, no Ollama)",
        )

    tries_per_provider = 2 if retry_same_provider else 1
    max_attempts = tries_per_provider * len(chain)

    result = LLMResult()
    errors: list[str] = []

    for provider in chain:
        handler = _HANDLERS.get(provider["kind"])
        if handler is None:
            errors.append(f"{provider['id']}: no handler for kind {provider['kind']!r}")
            continue

        for _ in range(tries_per_provider):
            if result.calls >= max_attempts:
                break
            result.calls += 1
            try:
                text = handler(provider, prompt, system, max_tokens, temperature)
            except Exception as exc:  # noqa: BLE001 - any failure => next provider
                errors.append(f"{provider['id']}: {type(exc).__name__}: {exc}")
                result.attempts.append(f"{provider['id']}=error")
                continue

            if not text:
                errors.append(f"{provider['id']}: empty completion")
                result.attempts.append(f"{provider['id']}=empty")
                continue

            result.text = text
            result.model = provider["model"]
            result.provider = provider["id"]
            result.status = "ok"
            result.notes = (
                f"{provider['label']} via {provider['model']}"
                + (" (input truncated)" if truncated else "")
                + (f" after {len(errors)} failure(s)" if errors else "")
            )
            result.attempts.append(f"{provider['id']}=ok")
            _record_usage(agent, provider, prompt, text, result.calls)
            return result

    result.status = config.STATUS_FAILED
    result.notes = "; ".join(errors)[: config.MAX_NOTE_CHARS]
    return result


def _record_usage(agent: str | None, provider: dict, prompt: str, text: str,
                  calls: int) -> None:
    """Best-effort ledger write for the zero-budget dashboard. Never raises."""
    try:
        db.record_usage(
            agent=agent or "unknown",
            provider=provider["id"],
            model=provider["model"],
            calls=calls,
            chars_in=len(prompt),
            chars_out=len(text),
        )
    except Exception:  # noqa: BLE001 - accounting must not break a run
        pass
