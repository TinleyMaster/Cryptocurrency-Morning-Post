from __future__ import annotations

import re


def extract_section(markdown_text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, markdown_text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""
