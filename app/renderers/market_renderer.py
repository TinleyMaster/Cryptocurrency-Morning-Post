from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class MarketRenderer:
    def __init__(self) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    def render_report(self, context: dict) -> str:
        return self.env.get_template("market_report.md.j2").render(**context)
