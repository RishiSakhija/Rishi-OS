"""Tests for the plain-code core.

No network, no database, no model calls. Everything here is deterministic
logic, which is exactly the part of Rishi-OS that should be tested hard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import caps, config, db, router, search, validator

AGENT_NAMES = (
    "research_agent",
    "growth_coach_agent",
    "summarize_librarian",
    "idea_strategist",
    "packaging_studio",
    "analytics_auditor",
    "ceo_supervisor",
)

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


# ---------------------------------------------------------------------------
# config.load_prompt / render_prompt
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", AGENT_NAMES)
def test_prompt_file_exists_for_every_agent(name):
    text = config.load_prompt(name)
    assert text, f"prompts/{name}.md is missing or empty"
    assert "{{BRAND}}" in text, f"prompts/{name}.md has no {{{{BRAND}}}} token"


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_agent_fallback_template_matches_file_tokens(name):
    """The inline fallback and the .md must expose the same tokens."""
    import importlib

    module = importlib.import_module(f"agents.{name}")
    fallback = getattr(module, "FALLBACK_TEMPLATE", "")
    assert fallback, f"{name} has no FALLBACK_TEMPLATE"

    def tokens(text):
        return set(re.findall(r"\{\{([A-Z_]+)\}\}", text))

    # Every token the inline fallback renders must also exist in the .md,
    # otherwise the file-based prompt would ship a literal {{TOKEN}} to the model.
    assert tokens(fallback) <= tokens(config.load_prompt(name))
    assert "BRAND" in tokens(fallback)


def test_load_prompt_missing_returns_empty():
    assert config.load_prompt("no_such_agent") == ""
    assert config.load_prompt("") == ""


def test_render_prompt_substitutes_tokens():
    assert config.render_prompt("A {{BRAND}} B {{CONTEXT}}", brand="X", context="Y") == "A X B Y"


def test_render_prompt_leaves_unknown_tokens_untouched():
    assert config.render_prompt("{{NOPE}}", brand="X") == "{{NOPE}}"


# ---------------------------------------------------------------------------
# core/search.py
# ---------------------------------------------------------------------------
def _stub_db(monkeypatch, seen=()):
    """Silence datahouse access inside search and capture the usage row."""
    captured: dict = {}
    monkeypatch.setattr(search.db, "is_duplicate", lambda **kw: kw.get("url") in seen)
    monkeypatch.setattr(search.db, "record_usage", lambda **kw: captured.update(kw))
    return captured


def test_web_search_returns_empty_for_blank_query():
    assert search.web_search("") == []
    assert search.web_search("   ") == []


def test_web_search_prefers_tavily_when_key_present(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        search, "_tavily",
        lambda q, n: [{"title": "T", "url": "https://a.test", "snippet": "s", "source": "tavily"}],
    )
    captured = _stub_db(monkeypatch)

    out = search.web_search("query", 5, agent="research_agent")

    assert [r["url"] for r in out] == ["https://a.test"]
    assert captured["provider"] == "tavily"
    assert captured["agent"] == "research_agent"


def test_web_search_falls_back_to_free_sources_without_key(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(
        search, "_free_search",
        lambda q, n: [{"title": "F", "url": "https://b.test", "snippet": "s", "source": "hackernews"}],
    )
    captured = _stub_db(monkeypatch)

    out = search.web_search("query")

    assert [r["url"] for r in out] == ["https://b.test"]
    assert captured["provider"] == "free_search"


def test_web_search_falls_back_when_tavily_raises(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")

    def boom(_query, _max):
        raise RuntimeError("tavily down")

    monkeypatch.setattr(search, "_tavily", boom)
    monkeypatch.setattr(
        search, "_free_search",
        lambda q, n: [{"title": "F", "url": "https://c.test", "snippet": "", "source": "reddit"}],
    )
    captured = _stub_db(monkeypatch)

    out = search.web_search("query")

    assert [r["source"] for r in out] == ["reddit"]
    assert captured["provider"] == "free_search"


def test_web_search_dedupes_seen_and_repeated_urls(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(
        search, "_free_search",
        lambda q, n: [
            {"title": "A", "url": "https://seen.test", "snippet": "", "source": "hackernews"},
            {"title": "B", "url": "https://new.test", "snippet": "", "source": "reddit"},
            {"title": "C", "url": "https://new.test", "snippet": "", "source": "google_news"},
        ],
    )
    _stub_db(monkeypatch, seen={"https://seen.test"})

    out = search.web_search("query")

    assert [r["url"] for r in out] == ["https://new.test"]


def test_web_search_respects_max_results(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(
        search, "_free_search",
        lambda q, n: [
            {"title": str(i), "url": f"https://x{i}.test", "snippet": "", "source": "reddit"}
            for i in range(10)
        ],
    )
    _stub_db(monkeypatch)

    assert len(search.web_search("query", max_results=3)) == 3


def test_web_search_survives_unreachable_datahouse(monkeypatch):
    """A dead datahouse must not lose search results entirely."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")

    def boom(**kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        search, "_free_search",
        lambda q, n: [{"title": "A", "url": "https://a.test", "snippet": "", "source": "reddit"}],
    )
    monkeypatch.setattr(search.db, "is_duplicate", boom)
    monkeypatch.setattr(search.db, "record_usage", boom)

    assert [r["url"] for r in search.web_search("q")] == ["https://a.test"]


def test_free_search_survives_every_source_failing(monkeypatch):
    def boom(_query, _max):
        raise RuntimeError("down")

    monkeypatch.setattr(search, "_hackernews", boom)
    monkeypatch.setattr(search, "_google_news", boom)
    monkeypatch.setattr(search, "_reddit", boom)

    assert search._free_search("query", 5) == []


def test_free_search_interleaves_sources(monkeypatch):
    monkeypatch.setattr(
        search, "_hackernews",
        lambda q, n: [{"title": "h1", "url": "https://h1", "snippet": "", "source": "hackernews"}],
    )
    monkeypatch.setattr(search, "_google_news", lambda q, n: [])
    monkeypatch.setattr(
        search, "_reddit",
        lambda q, n: [{"title": "r1", "url": "https://r1", "snippet": "", "source": "reddit"}],
    )

    assert [r["url"] for r in search._free_search("q", 5)] == ["https://h1", "https://r1"]


def test_as_prompt_block_handles_empty_and_populated():
    assert "no fresh web results" in search.as_prompt_block([])

    block = search.as_prompt_block(
        [{"title": "T", "url": "https://a.test", "snippet": "S", "source": "tavily"}]
    )
    assert "T" in block and "https://a.test" in block and "S" in block


def test_as_prompt_block_respects_input_ceiling():
    big = [
        {"title": "T" * 500, "url": "https://a.test", "snippet": "S" * 900, "source": "tavily"}
        for _ in range(50)
    ]
    block = search.as_prompt_block(big)
    assert len(block) <= config.MAX_INPUT_CHARS


# ---------------------------------------------------------------------------
# Blueprint compliance regressions
# ---------------------------------------------------------------------------
def _seed_line(agent: str) -> str:
    sql = (REPO_ROOT / "schema.sql").read_text(encoding="utf-8")
    matches = [ln for ln in sql.splitlines() if ln.strip().startswith(f"('{agent}'")]
    assert matches, f"no seed row for {agent}"
    return " ".join(matches)


def test_analytics_auditor_seed_is_weekly():
    assert "'weekly'" in _seed_line("analytics_auditor")


def test_ceo_supervisor_seed_is_daily():
    assert "'daily'" in _seed_line("ceo_supervisor")


def test_weekly_workflow_is_sunday_evening():
    text = (REPO_ROOT / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
    assert "0 18 * * 0" in text
    assert "analytics_auditor" in text
    assert "ceo_supervisor" not in text


def test_daily_workflow_runs_blueprint_order():
    text = (REPO_ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    # Parse actual `run: python ...` steps, not prose in the header comment.
    runs = re.findall(r"run: python (.+)", text)

    assert runs == [
        "scripts/daily_reset.py",
        "-m agents.growth_coach_agent",
        "-m agents.research_agent",
        "-m agents.idea_strategist",
        "-m agents.packaging_studio",
        "-m agents.summarize_librarian",
        "-m agents.ceo_supervisor",
    ]
    assert "analytics_auditor" not in text


def test_poller_drains_queue_then_runs_librarian():
    text = (REPO_ROOT / ".github/workflows/poller.yml").read_text(encoding="utf-8")
    runs = re.findall(r"run: python (.+)", text)
    assert runs == [
        "scripts/run_queued_tasks.py",
        "-m agents.summarize_librarian",
    ]


def test_readme_mermaid_block_one_is_complete():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```mermaid\n(.*?)```", readme, re.DOTALL)
    assert len(blocks) == 3

    first = blocks[0]
    for edge in ("CRON --> Core", "Core --> Roster", "Roster <--> DB", "DB <--> ST", "ST -->|"):
        assert edge in first, f"mermaid block 1 missing edge: {edge}"


def test_logger_has_no_dead_schema_ready_constant():
    source = (REPO_ROOT / "core" / "logger.py").read_text(encoding="utf-8")
    assert "_SCHEMA_READY" not in source


def test_queue_drain_covers_every_agent():
    import importlib

    module = importlib.import_module("scripts.run_queued_tasks")
    assert set(module.AGENT_MODULES) == set(AGENT_NAMES)
