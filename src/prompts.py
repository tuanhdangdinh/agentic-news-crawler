"""Load and render Jinja2 prompt templates from the prompts/ directory."""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, **context: object) -> str:
    """Render a Jinja2 template from the prompts/ directory.

    Args:
        template_name: Filename of the template, e.g. "system.j2".
        **context: Variables injected into the template.

    Returns:
        Rendered string.
    """
    template = _env.get_template(template_name)
    result = template.render(**context)
    logger.debug("rendered template: %s — %d chars", template_name, len(result))
    return result
