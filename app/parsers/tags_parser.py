from __future__ import annotations


def parse_tags(tags: list[str]) -> dict[str, list[str]]:
    buckets = {"KOL": [], "Topic": [], "Asset": [], "Type": [], "Date": []}
    for tag in tags:
        if not tag.startswith("#") or "/" not in tag:
            continue
        key, value = tag[1:].split("/", 1)
        buckets.setdefault(key, []).append(value)
    return buckets
