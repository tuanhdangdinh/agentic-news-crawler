"""Shared CSS and JavaScript for the Gradio interface."""

from __future__ import annotations

# Runs once on page load; defines selection and filtering for the split result view.
_RESULT_JS = """
() => {
  window.rtSelect = function(row, id) {
    const wrap = row.closest('.rt-split-wrap');
    if (!wrap) return;

    // Clear previous selection
    wrap.querySelectorAll('.rt-row-selected').forEach(r => r.classList.remove('rt-row-selected'));
    wrap.querySelectorAll('.rt-det-active').forEach(d => d.classList.remove('rt-det-active'));

    // Set new selection
    row.classList.add('rt-row-selected');
    const det = document.getElementById(id);
    if (det) {
      det.classList.add('rt-det-active');
      // Scroll detail panel to top when switching
      det.closest('.rt-detail-content').scrollTop = 0;
    }
  };

  window.rtFilter = function(input) {
    const q = input.value.toLowerCase().trim();
    const wrap = input.closest('.rt-split-wrap');
    if (!wrap) return;

    let visible = 0;
    let firstMatch = null;

    wrap.querySelectorAll('.rt-row').forEach(row => {
      const match = !q || (row.dataset.search || '').includes(q);
      row.style.display = match ? '' : 'none';
      if (match) {
        visible++;
        if (!firstMatch) firstMatch = row;
      }
    });

    const countEl = wrap.querySelector('.rt-count');
    if (countEl) countEl.textContent = visible + (visible === 1 ? ' result' : ' results');

    // If current selection is hidden, select the first visible match
    const selected = wrap.querySelector('.rt-row-selected');
    if (selected && selected.style.display === 'none' && firstMatch) {
      rtSelect(firstMatch, firstMatch.dataset.det);
    }
  };

  window.rtToggleFigure = function(button) {
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    target.hidden = expanded;
  };

  window.rtShowFigures = function(button) {
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    target.hidden = expanded;
    const collapsedLabel = button.dataset.collapsedLabel;
    const expandedLabel = button.dataset.expandedLabel;
    button.textContent = expanded ? collapsedLabel : expandedLabel;
  };
}
"""

CUSTOM_CSS = """
:root {
  --crawler-ink: #18231f;
  --crawler-muted: #627069;
  --crawler-accent: #c94f2d;
  --crawler-bg-soft: #fbfbfa;
  --crawler-border: rgba(24, 35, 31, 0.08);
  --crawler-radius: 16px;
  --crawler-shadow: 0 10px 30px rgba(24, 35, 31, 0.05);
}
.gradio-container {
  max-width: 1280px !important;
  background-color: #f8faf9 !important;
}
.hero {
  padding: 2.5rem 0 1.5rem;
}
.hero h1 {
  color: var(--crawler-ink);
  font-size: clamp(2.2rem, 6vw, 4.2rem);
  letter-spacing: -0.06em;
  line-height: 0.92;
  margin: 0;
}
.hero p {
  color: var(--crawler-muted);
  font-size: 1.15rem;
  max-width: 760px;
  margin-top: 0.75rem;
}
.run-button {
  background: var(--crawler-accent) !important;
  border-color: var(--crawler-accent) !important;
  box-shadow: 0 4px 14px rgba(201, 79, 45, 0.25) !important;
}
.primary-panel {
  border: 1px solid var(--crawler-border) !important;
  border-radius: var(--crawler-radius) !important;
  background: white !important;
  padding: 1.25rem !important;
  box-shadow: var(--crawler-shadow) !important;
}
.primary-panel-title {
  color: var(--crawler-ink);
  font-size: 0.85rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  margin: 0 0 0.25rem;
  text-transform: uppercase;
}
/* Minimal preset picker shown below supported fields. */
.sample-strip {
  gap: 0.5rem !important;
  flex-wrap: wrap !important;
  align-items: flex-start !important;
  margin: -0.12rem 0 0.82rem !important;
  padding: 0 !important;
  min-height: 0 !important;
}
.sample-tag {
  background: white !important;
  border: 1px solid var(--crawler-border) !important;
  color: var(--crawler-muted) !important;
  border-radius: 999px !important;
  padding: 0.35rem 0.75rem !important;
  font-size: 0.72rem !important;
  font-weight: 600 !important;
  line-height: 1 !important;
  cursor: pointer !important;
  min-width: unset !important;
  height: auto !important;
  transition: all 0.2s ease;
}
.sample-tag:hover {
  border-color: var(--crawler-accent) !important;
  color: var(--crawler-accent) !important;
  background: rgba(201, 79, 45, 0.03) !important;
  transform: translateY(-1px);
}
/* ── Shared badges / chips ───────────────────────────── */
.status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.35rem 0.85rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.status-ok  { background: #e9f6ef; color: #166534; }
.status-warn{ background: #fef9c3; color: #854d0e; }
.status-err { background: #fee2e2; color: #991b1b; }

.chip-list { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip {
  background: #f2f4f3;
  border-radius: 8px;
  padding: 0.3rem 0.7rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #4e5b55;
}
.kv-block { display: flex; flex-direction: column; gap: 0.5rem; }
.kv-row {
  display: flex;
  background: #f7f8f7;
  padding: 0.5rem 0.8rem;
  border-radius: 8px;
}
.kv-key {
  font-weight: 800;
  color: var(--crawler-muted);
  width: 110px;
  flex-shrink: 0;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.error-text { color: #991b1b; font-size: 0.85rem; background: #fee2e2; padding: 0.75rem; border-radius: 8px;}
.missing { color: var(--crawler-muted); font-style: italic; opacity: 0.5; }

/* ── Split result view ──────────────────────────────── */
.rt-empty {
  padding: 5rem;
  color: var(--crawler-muted);
  text-align: center;
  background: white;
  border-radius: var(--crawler-radius);
  border: 1px dashed var(--crawler-border);
}
.rt-split-wrap {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.6fr);
  gap: 1.5rem;
  background: var(--crawler-bg-soft);
  border: 1px solid var(--crawler-border);
  border-radius: 20px;
  padding: 1.25rem;
  box-shadow: var(--crawler-shadow);
  height: 720px;
}
@media (max-width: 1024px) {
  .rt-split-wrap { grid-template-columns: 1fr; height: auto; }
}
.rt-master {
  display: flex;
  flex-direction: column;
  background: white;
  border: 1px solid var(--crawler-border);
  border-radius: 16px;
  overflow: hidden;
}
.rt-toolbar {
  display: flex;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--crawler-border);
  gap: 1rem;
}
.rt-search {
  flex: 1;
  border: 1px solid var(--crawler-border);
  border-radius: 10px;
  padding: 0.65rem 1rem;
  font-size: 0.9rem;
}
.rt-search:focus {
  outline: none;
  border-color: var(--crawler-accent);
  box-shadow: 0 0 0 3px rgba(201, 79, 45, 0.1);
}
.rt-count {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--crawler-muted);
  background: #f2f4f3;
  padding: 0.4rem 0.8rem;
  border-radius: 99px;
}
.rt-table-scroll {
  flex: 1;
  overflow: auto;
}
.rt {
  width: 100%;
  border-collapse: collapse;
}
.rt th {
  position: sticky;
  top: 0;
  background: #f2f4f3;
  color: #59645f;
  text-align: left;
  padding: 0.85rem 1rem;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  z-index: 10;
}
.rt-row {
  cursor: pointer;
  border-bottom: 1px solid #f2f4f3;
  transition: all 0.2s ease;
}
.rt-row:hover { background: #fbfbfa; }
.rt-row-selected {
  background: #fff7f4 !important;
  box-shadow: inset 3px 0 var(--crawler-accent);
}
.rt-cell {
  padding: 1.15rem 1rem;
  font-size: 0.85rem;
  font-weight: 500;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rt-row-selected .rt-cell {
  font-weight: 600;
  color: var(--crawler-ink);
}

/* Detail Pane */
.rt-detail-pane {
  display: flex;
  flex-direction: column;
  background: white;
  border: 1px solid var(--crawler-border);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0,0,0,0.02);
}
.rt-detail-header {
  padding: 1rem 1.25rem;
  background: #fbfbfa;
  border-bottom: 1px solid var(--crawler-border);
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--crawler-muted);
}
.rt-detail-content {
  flex: 1;
  overflow-y: auto;
  position: relative;
}
.rt-det-item { display: none; padding: 1.5rem; }
.rt-det-active { display: block; animation: fadeIn 0.2s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

/* Re-use result-detail styles from before but refined */
.result-detail-header { margin-bottom: 2rem; }
.result-detail-fields dt {
  font-weight: 800;
  color: var(--crawler-muted);
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-top: 0.5rem;
}
.result-detail-fields dd {
  margin: 0.25rem 0 1rem;
  line-height: 1.6;
}
.result-detail-fields dd a { color: var(--crawler-accent); text-decoration: none; font-weight: 600; }
.result-detail-fields dd a:hover { text-decoration: underline; }

.figures-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  border: 1px solid #f2f4f3;
  border-radius: 8px;
  overflow: hidden;
}
.figures-table th { background: #fbfbfa; padding: 0.6rem 0.8rem; text-align: left; color: var(--crawler-muted); border-bottom: 1px solid #f2f4f3; }
.figures-table td { padding: 0.6rem 0.8rem; border-bottom: 1px solid #f2f4f3; }
.figures-more { background: #fbfbfa; color: var(--crawler-muted); text-align: center; font-size: 0.75rem; padding: 0.5rem; font-style: italic; }

.financial-ledger {
  border: 1px solid var(--crawler-border);
  border-radius: 10px;
  overflow: hidden;
}
.financial-figure {
  border-bottom: 1px solid var(--crawler-border);
}
.financial-figure:last-child {
  border-bottom: 0;
}
.financial-figure-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem 0.85rem;
}
.financial-figure-label {
  color: var(--crawler-ink);
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.35;
}
.financial-figure-meta {
  color: var(--crawler-muted);
  font-size: 0.7rem;
  margin-top: 0.2rem;
}
.financial-figure-value {
  color: var(--crawler-accent);
  font-size: 0.82rem;
  font-weight: 800;
  text-align: right;
}
.financial-figure-toggle,
.financial-figure-more {
  border: 1px solid var(--crawler-border);
  background: var(--crawler-bg-soft);
  color: var(--crawler-muted);
  cursor: pointer;
}
.financial-figure-toggle {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 6px;
  transition: transform 0.15s ease;
}
.financial-figure-toggle[aria-expanded="true"] {
  transform: rotate(180deg);
}
.financial-figure-toggle:focus-visible,
.financial-figure-more:focus-visible {
  outline: 2px solid var(--crawler-accent);
  outline-offset: 2px;
}
.financial-figure-context {
  padding: 0.65rem 0.85rem;
  border-left: 2px solid var(--crawler-accent);
  background: rgba(201, 79, 45, 0.06);
  color: var(--crawler-muted);
  font-size: 0.75rem;
  line-height: 1.5;
}
.financial-figure-more {
  width: 100%;
  padding: 0.6rem;
  border-width: 1px 0 0;
  font-size: 0.75rem;
  font-weight: 700;
}
@media (max-width: 640px) {
  .financial-figure-main {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .financial-figure-toggle {
    grid-column: 2;
  }
}
"""
