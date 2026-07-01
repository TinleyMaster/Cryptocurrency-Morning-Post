from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KolProfile:
    username: str
    role: str
    category: str
    group_name: str
    enabled: bool = True
