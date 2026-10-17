# AGENTS.md — Rishi-OS Rulebook (Permanent, All Sessions)

> **This file is binding for every agent, script, workflow, and OpenCode session in this repository.**
> When in doubt, choose the boring, cheap, deterministic option. If a change would add a dependency,
> an API call, or a loop, justify it in the PR description or don't make it.

Rishi-OS is an **autonomous multi-agent operating system for startups & personal growth (zero-budget edition)**.
Seven agents run on a schedule, think with an LLM exactly once per run, and write drafts to Postgres.
A human approves everything through a Streamlit dashboard that contains no AI.

---

## 1. Plain Code First

Routine work is **plain Python**. AI is used **only for thinking and writing**.

| Always plain Python | AI (LLM) only for |
|---|---|
| Scheduling & cron | Drafting copy |
| Database reads/writes | Reordering / prioritising |
| Counting, tallying, capping | Summarising prose |
| SHA-256 hashing | Angle / idea generation |
| De-duplication (hash + URL match) | Critique & self-review |
| Templating, trimming, formatting | Judgement calls |
| Retry-once logic, telemetry | |

**Test:** if the transformation is deterministic, it must not touch the model. No exceptions.
A summariser that "cleans up" text with an LLM when `.strip()` would do is a bug.

## 2. One Model Call Per Run

Fixed workflows beat free-roaming loops.

- **Exactly one** `router.call_llm()` per agent run. Not two, not "one plus a retry agent".
- **No agent frameworks.** No LangChain, no CrewAI, no AutoGen, no LangGraph. Direct SDK / REST calls only.
- Agents are linear scripts: read → build prompt → one call → validate → write. No planning loops,
  no tool-calling rounds, no reflection passes.
- The single permitted exception is a **transport-level** retry of the *same* call (see Rule 5).

## 3. Hard Caps & Small Inputs

Every agent, **before it does anything else**, asks the cap checker for permission.

- Check `enabled` **and** `runs_today < daily_cap` for its own row in the `agents` table.
- If not allowed: log the skip reason and exit `0`. Never error, never force the run.
- **Trim every input to < 4,000 characters.** Truncate deliberately and mark the cut
  (e.g. `input_truncated: true` in telemetry) rather than silently losing context.
- Send the model only what it needs. **Never send whole logs, whole tables, or whole HTML pages.**
- Hard ceilings: `MAX_STEPS`, `MAX_INPUT_CHARS = 4000`, `MAX_RUNS_PER_DAY` — all enforced in `core/caps.py`.

## 4. Shared Model Router — `core/router.py`

There is **one** router. No agent may be tied to a single provider or hold its own API key.

Fallback chain, tried in order:

```
Provider A  DeepSeek        →  (A-fallback) NVIDIA NIM
Provider B  Google Gemini
Provider C  Groq
Local       Ollama          →  keyless last resort
```

- All agents call `core.router.call_llm()` and never `requests.post()` to a model endpoint directly.
- The router owns provider selection, key lookup, timeouts, and the retry-once rule.
- The router returns a normalised result: `{text, model, provider, calls, status}`.
- Adding a provider means editing `core/router.py` **only**.

## 5. Fail Cheap

- **Retry once** on failure. Then stop. No exponential backoff ladders, no retry loops.
- On final failure: write `status="failed"` to the `logs` table with the error string, and
  **exit with code `0`** so GitHub Actions never fails the job or re-triggers a loop.
- A failed run must never write a partial/empty row to `outputs`.
- Never let an unhandled exception escape an agent's `main()`. Catch, log, exit `0`.

## 6. Human Approval & Dashboard Separation

- **Agents never publish.** All generated content is saved as `status="draft"` or `status="needs_review"`.
  There is no code path in this repo that posts to an external platform.
- The Streamlit dashboard (`/dashboard`) contains **ZERO AI**:
  - No model imports, no `router` import, no LLM calls, ever.
  - It **never executes an agent** directly. It may only flip flags / enqueue rows in Supabase.
  - It strictly **reads and writes Supabase**: view data, approve/reject drafts, edit, toggle caps.
- To "trigger" work, the dashboard writes a row or a flag. GitHub Actions picks it up.
  The dashboard is a control surface, not a runtime.

## 7. Standard 5-Step Agent Pattern (mandatory)

Every file in `/agents` implements exactly this shape, in this order:

| # | Step | Call |
|---|------|------|
| 1 | Cap check | `core.caps.check_can_run(agent_name)` |
| 2 | Brand load + plain-code fetch | `core.brands.load_brand(key)` then filter/dedupe in plain Python |
| 3 | **One** model call | `core.router.call_llm(prompt, ...)` |
| 4 | Validate + persist | `core.validator.validate_output(...)` → save raw **and** clean to `outputs` |
| 5 | Telemetry | `core.logger.log_run(agent, time, status, model, calls, notes)` |

```python
# canonical agent shape — do not deviate
def main() -> int:
    if not caps.check_can_run(AGENT):          # 1
        logger.log_run(AGENT, status="skipped", notes="cap_reached")
        return 0

    brand = brands.load_brand(BRAND_KEY)       # 2
    items = fetch_and_dedupe(brand)            # plain code, trimmed < 4000 chars

    result = router.call_llm(prompt, ...)      # 3  one call

    clean = validator.validate_output(result.text)   # 4
    db.save_output(AGENT, raw=result.text, clean=clean, status="draft")

    logger.log_run(                              # 5
        AGENT, status="ok", model=result.model,
        calls=result.calls, notes=f"items={len(items)}",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail cheap: Rule 5
        logger.log_run(AGENT, status="failed", notes=str(exc)[:500])
        sys.exit(0)
```

---

## Repository Layout

```
Rishi-OS/
├── core/            # shared, agent-agnostic plumbing (router, search, caps, brands, validator, logger, db)
├── agents/          # the 7 agents — each one thin, linear, 5-step
├── prompts/         # one .md template per agent, loaded via config.load_prompt
├── dashboard/       # Streamlit control room — ZERO AI, read/write Supabase only
├── .github/workflows/  # serverless cron: daily / weekly (Sun 18:00) / 20-minute poller
├── scripts/         # daily_reset.py, run_queued_tasks.py
├── schema.sql       # the 7 tables
├── AGENTS.md        # this file
└── requirements.txt
```

## The 7-Agent Roster

| # | Agent | Purpose |
|---|-------|---------|
| 1 | Research Agent | Find & dedupe fresh signal on a topic |
| 2 | Growth Coach Agent | Personal progress / habit coaching |
| 3 | Summarize Librarian | Compress long-form input into a library entry |
| 4 | Idea Strategist | Turn signal into ranked content angles |
| 5 | Packaging Studio | Draft platform-ready posts from one angle |
| 6 | Analytics Auditor | Read metrics, report what worked |
| 7 | CEO Supervisor | Weekly cross-agent review & prioritisation |

## Data Conventions

- **`status`** is one of: `draft`, `needs_review`, `approved`, `rejected`, `failed`, `skipped`.
- **`outputs`** stores `raw` (verbatim model text) **and** `clean` (validated) plus a `hash` for dedupe.
- **`logs`** is append-only telemetry: `agent`, `time`, `status`, `model`, `calls`, `notes`.
- De-duplicate on **SHA-256 of normalised content** *and* **URL match**. Both, not either.

## Non-Negotiables (blocking review checklist)

- [ ] One model call per run.
- [ ] Input trimmed below 4,000 characters.
- [ ] `enabled` + `daily_cap` checked first.
- [ ] Model access goes through `core/router.py` only.
- [ ] Failures log `status="failed"` and exit `0`.
- [ ] Output saved as `draft` / `needs_review` — never published.
- [ ] No AI import anywhere under `/dashboard`.
- [ ] No LangChain / CrewAI / agent framework added.
