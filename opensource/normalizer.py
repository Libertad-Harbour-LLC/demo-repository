"""Cross-source name aggregation for the Open Source radar.

Thin wrapper around ``trendwatch.normalizer.normalize`` with a vocabulary
biased toward deployable OSS product/platform names. Single GitHub source for
now, so cross-source counts are mostly 1 — kept for parity + future Reddit.
"""
from __future__ import annotations

from trendwatch import normalizer as _base

KNOWN_TOOLS: list[str] = [
    "open source",
    "self-hosted",
    "self-hostable",
    "alternative",
    "docker",
    "boilerplate",
]


def normalize(items_by_source):
    saved = list(_base.KNOWN_TOOLS)
    try:
        _base.KNOWN_TOOLS[:] = KNOWN_TOOLS
        return _base.normalize(items_by_source)
    finally:
        _base.KNOWN_TOOLS[:] = saved


__all__ = ["KNOWN_TOOLS", "normalize"]
