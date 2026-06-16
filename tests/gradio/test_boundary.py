"""The UI package must not import the engine or its heavy dependencies."""

from __future__ import annotations

import ast
from pathlib import Path

import crawl_tool.gradio

_FORBIDDEN = ("crawl_tool.engine", "crawl_engine", "crawl4ai", "playwright", "anthropic")
_PACKAGE_DIR = Path(crawl_tool.gradio.__file__).parent


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_engine_imports_in_gradio_package():
    offenders: dict[str, set[str]] = {}
    for path in _PACKAGE_DIR.rglob("*.py"):
        forbidden = _imported_roots(path) & set(_FORBIDDEN)
        if forbidden:
            offenders[path.name] = forbidden

    assert not offenders, f"forbidden imports found: {offenders}"
