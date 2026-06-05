# Documentation Style Guide

---

## Purpose

This guide defines the exact format for every document type in this project.
Follow it literally when writing or generating docs — the goal is that any two documents
of the same type look identical in structure.

---

## Markdown Formatting Rules

Apply these rules to every document without exception:

- One blank line before and after every heading, list, table, code fence, and `---`
- `---` separates top-level `##` sections only — never between `###` subsections
- Heading levels must be sequential — never jump from `##` to `####`
- Nested list items use two-space indentation
- Every code block carries a language tag — ` ```python `, ` ```bash `, ` ```json `, ` ```mermaid `
- Table columns align with `|---|---|` (no padding spaces in the separator row)

---

## Document Header

Every document begins with this block — no content before it:

```markdown
# <Title>

**Prepared:** YYYY-MM-DD

**Revision history:**
- Initial draft: <one-line description>
- Rev 2: <what changed>

**commit:** [link](<commit-url>)
```

Rules:

- `**Prepared:**` is the date the initial draft was written — never updated
- Each revision is one line: `- Rev N: <what changed>` for revisions after the initial draft; a `(YYYY-MM-DD)` prefix after the number is optional — include it when the date adds value, omit it otherwise
- The initial draft line has no date prefix
- `**commit:**` is the only optional metadata field allowed; place it as the last line of the header block, after the revision history, and link to the commit that introduced the document's current state
- No other metadata fields in the header block

---

## Weekly Report Structure

Use this section order exactly — do not add, remove, or rename sections:

```
# Week N <Type> Report — <Short Title>
**Prepared:** ...
**Revision history:** ...
---
## Overview
### What Week N Builds
### What Changed From Week N-1
### Data Flow This Week
    ```mermaid ...```
### This Report
---
## Objective
---
## Module: `src/<file>.py`
### Design Decisions
### Public Interface
---
## Smoke Test
---
## Known Limitations
---
## Dependency Changes
---
## Week N+1 Entry Criteria
```

Section rules:

- **Overview / What Week N Builds** — 2–4 bullets; what problem this week solves
- **Overview / What Changed From Week N-1** — bullet per file changed; format: `filename — old state → new state`
- **Overview / Data Flow This Week** — one Mermaid `flowchart TD` diagram; nodes labelled with filename and role
- **Overview / This Report** — one sentence stating the report's scope
- **Objective** — bullet list of concrete deliverables; each bullet is a verb phrase
- **Module** — one `## Module:` section per file implemented; contains Design Decisions then Public Interface
- **Smoke Test** — command block, actual output block, acceptance criteria table
- **Known Limitations** — bullet per limitation; each ends with when it will be addressed
- **Dependency Changes** — table with columns `Change | Reason`; write `No new dependencies` if none
- **Week N+1 Entry Criteria** — checklist; `- [x]` for done, `- [ ]` for not done

Research-only weeks replace **Module** and **Smoke Test** with:

```
## Sources Checked
## Comparison Matrix
## Decision
## Risks and Mitigations
```

---

## Module Section Format

Each `## Module:` section follows this structure:

```markdown
## Module: `src/<file>.py`

### Design Decisions

- Decision 1 — reason
- Decision 2 — reason

### Public Interface

\`\`\`python
def function_name(arg: type) -> ReturnType
\`\`\`

- Bullet describing behaviour
- Edge case or failure mode
```

Rules:

- Design Decisions come before Public Interface — always
- Each design decision bullet states the decision and the reason separated by ` — `
- Public Interface shows the signature in a code block, then behaviour bullets below it

---

## Acceptance Criteria Table

Every smoke test section contains this table:

```markdown
| Check | Expected | Actual |
|---|---|---|
| <what is verified> | <expected value or behaviour> | <actual result and pass/fail symbol> |
```

- Pass: append ` ✓`
- Fail: append ` ✗` and add a follow-up note

---

## Diagrams

- Use Mermaid for all data flow diagrams — `flowchart TD` for top-down, `flowchart LR` for left-right
- One diagram per report, placed in **Overview / Data Flow This Week**
- Every node label contains the filename and its role, separated by `<br>`

```
CLI["main.py <br> CLI entry point"]
```

---

## Docstrings

Google style on every public function and class:

```python
def fetch_page(url: str, css_selector: str | None = None) -> PageResult:
    """Fetch a URL and return structured page content.

    Args:
        url: Absolute URL to fetch.
        css_selector: Optional CSS selector to scope content extraction.

    Returns:
        PageResult with markdown, links, and metadata. Never raises.
    """
```

Rules:

- One-line summary first — ends with a period
- Blank line between summary and Args
- Args and Returns: short phrase per item, not sentences
- No Raises section unless the function deliberately raises as part of its contract

---

## Tables

Use a table when the content has two or more attributes per item. Common patterns:

| Table type | Required columns |
|---|---|
| CLI flags | `Flag \| Default \| Description` |
| Acceptance criteria | `Check \| Expected \| Actual` |
| Dependency changes | `Change \| Reason` |
| Comparison matrix | one column per option, one row per criterion |
| Module field reference | `Field \| Type \| Description` |

Cell content: one phrase — not a full sentence, not a paragraph.

---

## Revision History

```markdown
**Revision history:**
- Initial draft: <one-line summary of what the initial draft covered>
- Rev 2: <what changed and why>
- Rev 3 (YYYY-MM-DD): <what changed and why>
```

- Revision numbers are sequential integers starting at 2 (the initial draft is not numbered)
- The `(YYYY-MM-DD)` date prefix is optional on each revision line — both `- Rev N:` and `- Rev N (YYYY-MM-DD):` are valid; do not mix arbitrarily, but a report may date later revisions and leave earlier ones undated
- Each revision line is one sentence maximum
- Historical reports must not be rewritten — add a revision entry instead

---

## Sources

- Link official docs, GitHub repos, PyPI pages, or primary papers — no bare domain names
- Label each source: `[Library name — official docs](url)`
- Separate verified facts from recommendations explicitly
- Include the library version when the API is version-sensitive

---

## Commit Messages

- Format: `type: summary` — Conventional Commits, no scope required unless helpful
- Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`
- Subject line under 72 characters
- No body paragraph — reasoning belongs in the PR description or report
- No `Co-Authored-By` trailer
