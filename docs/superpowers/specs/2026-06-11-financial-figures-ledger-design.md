# Financial Figures Ledger Design

**Prepared:** 2026-06-11

**Revision history:**
- Initial draft: approved compact-ledger design for key financial figures

---

## Purpose

Make `key_financial_figures` easier to scan in the selected-record detail panel without
changing extracted data, crawl output, or the rendering of other structured fields.

The ledger should emphasize the metric and value first, keep supporting metadata visible,
and reveal long context only when requested.

---

## Scope

The result detail panel will provide:

- A specialized compact ledger for the `key_financial_figures` field
- One ledger row per financial figure
- Prominent values and readable metric labels
- Muted entity and period metadata
- An expandable context section when context is present
- An initial limit of 12 rows with a control to reveal remaining figures
- Graceful rendering for both observed financial-figure schemas

Other list-of-object fields will continue using the existing generic table renderer.

The change will not add sorting, filtering, editing, charting, value normalization, or
changes to the downloaded crawl payload.

---

## Ledger Layout

Each financial figure appears as one compact row:

```text
Metric or figure label                         Value  [expand]
Entity · Period
```

The row uses this visual hierarchy:

- Metric or figure label — primary left-aligned text
- Value — bold right-aligned accent text
- Entity and period — muted metadata below the label
- Expand control — keyboard-accessible disclosure affordance
- Context — full-width muted panel below the row when expanded

Rows use subtle separators rather than individual card borders so that articles containing
20 or more figures remain compact.

---

## Data Mapping

The renderer supports the observed schemas without changing the extraction contract.

| Display element | Preferred keys | Fallback |
|---|---|---|
| Label | `metric`, `figure` | First non-value scalar field |
| Value | `value` | Em dash |
| Entity | `entity` | Omitted |
| Period | `period` | Omitted |
| Context | `context` | No disclosure control |

Entity and period are joined with a centered separator only when both values exist. Null,
empty, or missing optional fields are omitted instead of producing empty placeholders.

Unknown extra keys remain available in the generic fallback representation if an item cannot
be mapped to a meaningful ledger label.

---

## Interaction

- Context is collapsed by default.
- A row with context includes a disclosure button.
- Activating the button expands only that row's context.
- Activating it again collapses the context.
- The button exposes expanded state through `aria-expanded`.
- Enter and Space activate the disclosure button.
- Rows without context do not display an inactive disclosure control.
- The first 12 figures are visible initially.
- When more figures exist, a `Show N more` control reveals all remaining rows.

The interaction is local browser behavior and does not mutate Gradio state or crawl data.

---

## Rendering Boundaries

`render_result_detail()` identifies `key_financial_figures` by field name and delegates it to
a dedicated renderer. All other list-of-object values continue through
`render_list_of_objects()`.

The dedicated renderer:

- Accepts a list of dictionaries
- Escapes every extracted value before inserting it into HTML
- Generates stable per-render disclosure identifiers
- Returns the existing missing-value treatment for an empty list
- Falls back safely when a figure has incomplete or unfamiliar keys

The existing master table remains unchanged. Its compact summary continues to show figure
labels rather than expanding one article into multiple table rows.

---

## Styling

Ledger styles remain scoped to the result detail panel.

- Borders use the existing neutral result-view palette.
- Values use the existing crawler accent color.
- Expanded context uses a restrained tinted background and left accent border.
- Hover and focus states provide non-color affordances.
- Long labels and values wrap rather than overflow the detail panel.
- On narrow screens, value and disclosure controls remain visible while metadata wraps below.

No new design tokens or external dependencies are required.

---

## Empty and Edge States

- Empty figure list — display the existing em dash placeholder
- Missing value — display an em dash
- Missing label — use a readable fallback key or `Financial figure`
- Missing entity and period — omit the metadata line
- Missing context — omit the disclosure control
- More than 12 entries — show the first 12 and a reveal control
- Non-dictionary list item — retain the existing generic list behavior
- Untrusted HTML in any field — render escaped text only

---

## Testing

Tests will verify:

- `key_financial_figures` uses the ledger renderer.
- Other list-of-object fields retain the generic table renderer.
- `metric/value/entity/period/context` maps to the expected hierarchy.
- `figure/value` renders without empty metadata or disclosure controls.
- Missing and null optional fields do not create empty visual elements.
- Context content and disclosure state use accessible markup.
- Values and context are HTML escaped.
- More than 12 figures produce the correct reveal control and hidden rows.
- Incomplete schemas receive stable fallbacks.

---

## Acceptance Criteria

| Check | Expected |
|---|---|
| Default presentation | Compact ledger rows in selected-record details |
| Scan hierarchy | Metric and value visible before supporting metadata |
| Context behavior | Hidden by default and expandable per figure |
| Schema support | Both observed schemas render without data changes |
| Large lists | First 12 rows visible with reveal control |
| Accessibility | Keyboard disclosure and explicit expanded state |
| Generic fields | Existing object-list table remains unchanged |
| Output compatibility | Raw JSON and downloaded payload remain unchanged |
