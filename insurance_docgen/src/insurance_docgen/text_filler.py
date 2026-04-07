"""Text template filler - renders Jinja2 templates from profile data.

Used for documents that don't have fillable PDF forms: loss run reports,
financial statements, board resolutions, GL supplementals.

Templates are Jinja2 (.txt.j2) files shipped with the package or
provided by the user.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


# Built-in text templates are shipped with the package
_TEMPLATES_DIR = Path(__file__).parent / "templates" / "text"


def render_text(
    template_name: str,
    data: dict[str, Any],
    output_path: str | Path,
    custom_templates_dir: str | Path | None = None,
) -> Path:
    """Render a text template with profile data.

    Args:
        template_name: Built-in template name (e.g., "loss_run") or
                       filename (e.g., "loss_run.txt.j2").
        data: Dict of values to fill into the template.
        output_path: Where to save the rendered text.
        custom_templates_dir: Optional directory to search for templates
                              before falling back to built-in templates.

    Returns:
        Path to the saved file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Normalize template name (add .txt.j2 suffix if missing)
    if not template_name.endswith(".j2"):
        template_name = f"{template_name}.txt.j2"

    # Set up Jinja2 with search path: custom dir first, then built-in
    search_paths = [str(_TEMPLATES_DIR)]
    if custom_templates_dir:
        search_paths.insert(0, str(custom_templates_dir))

    env = Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=select_autoescape([]),  # No escaping for plain text
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Add custom filters for formatting
    env.filters["currency"] = _format_currency
    env.filters["pct"] = _format_pct

    template = env.get_template(template_name)
    rendered = template.render(**data)

    output_path.write_text(rendered)
    return output_path


def _format_currency(value: float | int | None) -> str:
    """Format a number as currency: 50000000 -> $50,000,000"""
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def _format_pct(value: float | None) -> str:
    """Format a decimal as percentage: 0.85 -> 85.0%"""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"
