# Documentation Style Guide

---

## General Rules

- **Prefer bullet points** for reports, decisions, checklists, and tradeoff summaries
- Use short paragraphs when explaining architecture or design reasoning
- **Concise** — one idea per bullet; cut filler words
- **Easy to understand** — write for someone picking up the file cold, not the author

---

## Docstrings

- Google style on every public function and class
- One-line summary first, then Args and Returns sections
- Args and Returns use short descriptions — not essays

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

---

## Weekly Report Structure

Each weekly report follows this order:

1. **Header** — title, date, revision history
2. **Overview** — what this week builds, what changed from last week, data flow diagram, report scope
3. **Objective** — bullet list of deliverables
4. **Modules** — one section per file; design decisions + public interface
5. **Smoke Test** — command, actual output, acceptance criteria table
6. **Known Limitations** — what is deferred and why
7. **Week N+1 Entry Criteria** — checklist of done vs. not-done items

Research-only weeks may replace **Modules** and **Smoke Test** with:

- **Sources Checked**
- **Comparison Matrix**
- **Decision**
- **Risks and Mitigations**

---

## Diagrams

- Use Mermaid for all data flow diagrams — `flowchart TD` or `flowchart LR`
- One diagram per report in the Overview section
- Label each node with the file name and its role

---

## Tables

- Use tables for: CLI flags, acceptance criteria, dependency changes, variable reference lists
- Keep cell content short — one phrase, not a sentence

---

## Revision History

- One line per meaningful change at the top of each report
- Format: `- Rev N: short description of what changed`

---

## Sources

- Link official docs, GitHub repos, PyPI pages, or primary papers
- Separate verified facts from recommendations
- Include version or prepared date when library APIs are unstable
- Avoid unsourced claims about library behavior

---

## Commit Messages

- Use **Conventional Commits** format: `type(scope): summary`
- Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`
- Keep the subject under 72 characters
- Prefer intent over file-by-file summaries
- No trailing summaries like "this commit adds..." or "changed X to Y"
