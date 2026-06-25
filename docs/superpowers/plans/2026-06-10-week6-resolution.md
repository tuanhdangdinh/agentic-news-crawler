# Week 6 Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Week 6 test, documentation, and handover deliverables accurate, reproducible, and ready for review.

**Architecture:** Strengthen live integration assertions without changing crawler behavior, then align architecture and README documentation with the current CLI, Gradio UI, and schema registry. Preserve historical reports by adding a revision and keep generated run artifacts out of Git.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, Ruff, Markdown, Mermaid, uv.

---

### Task 1: Integration Acceptance Tests

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Replace tautological assertions**

Track real `src.agent.fetch_page` calls, require the depth-zero crawl to fetch only the seed, compare normalized hostnames, require at least one dated article, and assert all requested extraction fields.

- [ ] **Step 2: Verify collection**

Run:

```bash
uv run pytest tests/test_integration.py --collect-only -q
```

Expected: 11 integration tests collected without import or syntax errors.

- [ ] **Step 3: Verify credential-free behavior**

Run:

```bash
uv run pytest -m integration -q
```

Expected: Anthropic-dependent tests skip when the API key is absent; standalone fetch tests remain selectable.

### Task 2: Architecture and README

**Files:**
- Modify: `docs/architecture.md`
- Modify: `README.md`

- [ ] **Step 1: Document current entry points**

Add `app.py` and `src/ui.py`, showing both CLI and Gradio paths into `AgentConfig`.

- [ ] **Step 2: Document schema selection**

Add `src/schema_registry.py` and the registered-schema-first, inferred-schema-fallback extraction flow.

- [ ] **Step 3: Correct stale limitations**

Replace the obsolete 2000s-only URL statement and update retry and integration-baseline wording.

### Task 3: Repository Cleanup

**Files:**
- Modify: `.gitignore`
- Delete: `integration_results.txt`
- Delete: `run.log`

- [ ] **Step 1: Ignore generated run evidence**

Add the two generated artifact names to `.gitignore`.

- [ ] **Step 2: Remove failed local artifacts**

Delete the untracked files so they cannot be mistaken for handover evidence.

### Task 4: Week 6 Report Revision

**Files:**
- Modify: `docs/reports/week6_implementation_report.md`

- [ ] **Step 1: Add a dated revision**

Describe stronger integration assertions, current documentation, repository cleanup, and verification status without rewriting historical claims.

- [ ] **Step 2: Record current verification**

Record the fresh non-integration and collection results. Keep live integration results explicitly historical unless rerun in this session.

### Task 5: Verification

**Files:**
- Verify all changed files

- [ ] **Step 1: Format and lint**

```bash
uv run ruff format tests/test_integration.py
uv run ruff check .
```

- [ ] **Step 2: Run non-integration tests**

```bash
uv run pytest -m "not integration"
```

- [ ] **Step 3: Check repository state**

```bash
git diff --check
git status --short
```

Expected: no formatting errors, no test failures, and no generated run artifacts.
