# Quick Crawl Conversation Design

**Prepared:** 2026-06-29

**Revision history:**
- Initial draft: Redesign Quick Crawl as a ChatGPT-like multi-turn crawl setup page.

---

## Overview

Quick Crawl changes from a two-phase form into a conversational page. On first visit, the page shows a centered prompt input that asks what to crawl. After the first message, the page becomes a chat workspace where the user can refine crawl settings through follow-up messages before starting the crawl.

The redesign is scoped to `src/crawl_tool/gradio/ui_quick_crawl.py` and shared styling in `src/crawl_tool/gradio/ui_styles.py`. It keeps the existing engine HTTP contract: `/parse` turns natural language into crawl fields, and `/crawl` starts the crawl.

---

## Goals

- Make first visit feel like a focused prompt surface, with the input centered in the main content area.
- Support multi-turn refinement before running a crawl.
- Show inferred crawl settings in the assistant response so users can review the request.
- Keep Advanced Crawl and Storage unchanged.
- Reuse the existing result rendering tabs after the crawl starts.

---

## User Experience

### First Visit

Quick Crawl opens with a centered prompt panel:

- Heading: `What should I crawl?`
- Supporting text: site, date range, article type, and fields to extract.
- Large text input with sample prompts underneath.
- A single send button.

The sidebar remains visible. No field form is shown before the first message.

### Conversation State

After the first prompt:

- The centered start screen is hidden.
- A chat transcript fills the page.
- User messages are right-aligned.
- Assistant messages are left-aligned.
- The assistant response includes a compact crawl settings summary.
- The input moves to a persistent bottom composer.
- A `Run crawl` button appears in the conversation header when `seed_url` is present.

Follow-up messages update the same draft crawl request instead of starting a separate crawl.

### Results State

When the user runs the crawl:

- The conversation remains above the run status and result tabs.
- The existing status markdown, download file, Extracted Data tab, and Raw JSON tab are reused.
- The result table behavior in `ui_results.py` is unchanged.

---

## Conversation Behavior

The page maintains three pieces of Gradio state:

| State | Type | Purpose |
|---|---|---|
| `conversation_state` | `list[dict[str, str]]` | Ordered user and assistant messages |
| `draft_request_state` | `dict` | Latest inferred crawl fields |
| `has_started_state` | `bool` | Whether to show first-visit or conversation layout |

When a user sends a message:

1. Append the user message to `conversation_state`.
2. Build a combined prompt from prior user messages and the current draft settings.
3. Call `parse_prompt()` with the combined prompt.
4. Merge returned fields into `draft_request_state`.
5. Append an assistant message that summarizes the updated settings.
6. Render the transcript HTML and update `Run crawl` visibility.

If `/parse` fails, the assistant appends an error message to the transcript and keeps the previous draft settings.

---

## Crawl Settings Summary

The assistant summary renders the fields users need to verify:

| Field | Source |
|---|---|
| Seed URL | `draft_request_state["seed_url"]` |
| Goal | `draft_request_state.get("goal", "")` |
| Date filter | `draft_request_state.get("date_filter", "")` |
| Extraction prompt | `draft_request_state.get("extract_prompt", "")` |
| Max pages | `draft_request_state.get("max_pages", 10)` |
| Max depth | `draft_request_state.get("max_depth", 1)` |

The summary is not an editable form in the first implementation. Users edit by sending another message, for example `limit it to banking and securities only` or `use max 25 pages`.

---

## Implementation Notes

Add focused helpers to `ui_quick_crawl.py`:

```python
def _merge_draft(existing: dict, parsed: dict) -> dict
def _conversation_prompt(messages: list[dict[str, str]], draft: dict) -> str
def _render_conversation(messages: list[dict[str, str]], draft: dict) -> str
def _run_button_visible(draft: dict) -> bool
```

`build_quick_crawl_page()` keeps ownership of event wiring. It should not import from engine modules and should continue to call only the Gradio client and shared UI helpers.

Shared CSS in `ui_styles.py` should add classes for:

- Centered first-visit surface.
- Chat transcript.
- User and assistant message bubbles.
- Settings summary grid.
- Bottom composer.

---

## Error Handling

- Empty first prompt shows an inline message in the centered prompt panel.
- Empty follow-up leaves the transcript unchanged.
- Engine connection errors render as assistant messages.
- Parse validation errors render as assistant messages.
- `Run crawl` remains hidden until a valid `seed_url` exists.

---

## Testing

Add or update Gradio unit tests for helper behavior:

- `_merge_draft()` preserves existing fields when parse omits them.
- `_merge_draft()` overwrites fields returned by parse.
- `_conversation_prompt()` includes prior user messages and current draft settings.
- `_render_conversation()` includes user messages, assistant messages, and crawl settings.
- `_run_button_visible()` is false without `seed_url` and true with a valid `seed_url`.

Existing crawl tests continue to cover `run_crawl()` and result rendering.

---

## Out Of Scope

- New engine endpoints.
- Streaming assistant responses.
- Editing settings through inline form controls.
- Persisting chat sessions.
- Changing Advanced Crawl, Storage, or result table behavior.
