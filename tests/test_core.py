"""Tests for the plain-code core.

No network, no database, no model calls. Everything here is deterministic
logic, which is exactly the part of Rishi-OS that should be tested hard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import caps, config, db, router, validator

REPO_ROOT = Path(__file__).resolve().parent.parent

KEY_ENVS = (
    "DEEPSEEK_API_KEY",
    "NVIDIA_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
def test_trim_marks_truncation():
    text, truncated = config.trim("abcdef", 3)
    assert text == "abc"
    assert truncated is True


def test_trim_leaves_short_text_alone():
    text, truncated = config.trim("abc", 10)
    assert text == "abc"
    assert truncated is False


def test_trim_handles_none():
    assert config.trim(None) == ("", False)


def test_input_ceiling_is_4000():
    assert config.MAX_INPUT_CHARS == 4000


# ---------------------------------------------------------------------------
# db -- hashing and de-duplication
# ---------------------------------------------------------------------------
def test_content_hash_is_stable():
    assert db.content_hash("hello world") == db.content_hash("hello world")


def test_content_hash_ignores_whitespace_and_case():
    assert db.content_hash("Hello   World") == db.content_hash("  hello world  ")


def test_content_hash_differs_on_real_change():
    assert db.content_hash("hello world") != db.content_hash("hello there")


# ---------------------------------------------------------------------------
# validator
# ---------------------------------------------------------------------------
GOOD = """## Signal
Something concrete happened.

## Why It Matters
Because the audience cares.

## Next Step
Ship it this week.
"""


def test_validate_output_accepts_matching_template():
    assert validator.validate_output(
        GOOD, required_sections=("Signal", "Why It Matters", "Next Step")
    ).startswith("## Signal")


def test_validate_output_rejects_missing_sections():
    with pytest.raises(validator.ValidationError, match="missing required sections"):
        validator.validate_output(GOOD, required_sections=("Signal", "Nonexistent"))


def test_validate_output_rejects_empty():
    with pytest.raises(validator.ValidationError, match="empty output"):
        validator.validate_output("   ")


def test_validate_output_rejects_too_short():
    with pytest.raises(validator.ValidationError, match="too short"):
        validator.validate_output("nope", min_chars=40)


def test_validate_output_strips_code_fences():
    fenced = "```markdown\n" + GOOD + "\n```"
    clean = validator.validate_output(fenced, required_sections=("Signal",))
    assert "```" not in clean


def test_sections_parses_headings():
    parsed = validator.sections(GOOD)
    assert set(parsed) == {"signal", "why it matters", "next step"}


def test_section_match_is_loose():
    loose = "## The Signal\nThis body is comfortably longer than forty characters.\n"
    assert validator.validate_output(loose, required_sections=("Signal",))


def test_fit_trims_to_ceiling():
    text, truncated = validator.fit("x" * 5000)
    assert len(text) == config.MAX_INPUT_CHARS
    assert truncated is True


# ---------------------------------------------------------------------------
# router -- provider chain selection
# ---------------------------------------------------------------------------
def test_chain_is_ollama_only_without_keys(monkeypatch):
    for name in KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    available = config.available_providers()
    assert [p["id"] for p in available] == ["ollama"]


def test_chain_follows_declared_order(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert [p["id"] for p in config.available_providers()] == [
        "deepseek",
        "gemini",
        "ollama",
    ]


def test_router_returns_failure_without_raising(monkeypatch):
    for name in KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:1")
    result = router.call_llm("ping")
    assert result.ok is False
    assert result.status == config.STATUS_FAILED


def test_router_rejects_empty_prompt():
    result = router.call_llm("   ")
    assert result.ok is False


# ---------------------------------------------------------------------------
# caps -- the gate
# ---------------------------------------------------------------------------
def test_caps_denies_unregistered_agent(monkeypatch):
    monkeypatch.setattr(caps.db, "get_agent", lambda name: None)
    allowed, reason = caps.explain("ghost_agent")
    assert allowed is False
    assert reason == "not_registered"


def test_caps_denies_disabled_agent(monkeypatch):
    monkeypatch.setattr(
        caps.db, "get_agent", lambda name: {"enabled": False, "daily_cap": 1, "runs_today": 0}
    )
    allowed, reason = caps.explain("research_agent")
    assert allowed is False
    assert reason == "disabled"


def test_caps_denies_at_daily_cap(monkeypatch):
    monkeypatch.setattr(
        caps.db, "get_agent", lambda name: {"enabled": True, "daily_cap": 2, "runs_today": 2}
    )
    allowed, reason = caps.explain("research_agent")
    assert allowed is False
    assert "daily_cap_reached" in reason


def test_caps_allows_under_cap(monkeypatch):
    monkeypatch.setattr(
        caps.db, "get_agent", lambda name: {"enabled": True, "daily_cap": 3, "runs_today": 1}
    )
    assert caps.check_can_run("research_agent") is True
    assert caps.remaining("research_agent") == 2


def test_caps_denies_when_registry_unreachable(monkeypatch):
    def boom(name):
        raise RuntimeError("db down")

    monkeypatch.setattr(caps.db, "get_agent", boom)
    allowed, reason = caps.explain("research_agent")
    assert allowed is False
    assert "registry_unavailable" in reason


# ---------------------------------------------------------------------------
# Rule 6 -- structural guarantees
# ---------------------------------------------------------------------------
def test_agents_may_never_publish():
    """save_output must refuse any status outside draft / needs_review."""
    with pytest.raises(ValueError, match="refusing to save"):
        db.save_output(agent="x", raw="a", clean="b", status="published")


def test_dashboard_contains_no_ai():
    """Rule 6: no AI import, and no agent execution, anywhere in /dashboard.

    Inspects real import statements via the AST rather than scanning prose, so
    a docstring that *describes* the prohibition cannot trip the check.
    """
    import ast

    source = (REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.update(f"{module}.{alias.name}" for alias in node.names)

    forbidden_roots = ("agents", "core.router", "core.validator")
    for module in imported:
        for root in forbidden_roots:
            assert not (
                module == root or module.startswith(root + ".")
            ), f"dashboard must not import {module}"

    # It may touch the datahouse, but never a model.
    assert "core.db" in imported, "dashboard should read/write via core.db"
    assert "call_llm" not in ast.dump(tree), "dashboard must not call the router"


def test_rulebook_exists_and_names_the_router():
    rulebook = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "core/router.py" in rulebook
    assert "One Model Call Per Run" in rulebook
