from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class DeepreadRenderer:
    def __init__(self) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(loader=FileSystemLoader(template_dir), autoescape=False, trim_blocks=True, lstrip_blocks=True)

    def render_report(self, context: dict) -> str:
        return self.env.get_template("deepread.md.j2").render(**context)
