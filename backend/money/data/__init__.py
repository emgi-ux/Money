"""Market data providers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .base import DataProvider, Fundamentals
from .synthetic import SyntheticProvider

__all__ = ["DataProvider", "Fundamentals", "SyntheticProvider", "get_provider"]


@lru_cache(maxsize=None)
def get_provider(name: str | None = None) -> DataProvider:
    """Build a provider by name ("yahoo" or "synthetic").

    Defaults to the ``MONEY_PROVIDER`` environment variable, else "synthetic".
    """
    name = (name or os.environ.get("MONEY_PROVIDER") or "synthetic").lower()
    if name == "synthetic":
        return SyntheticProvider()
    if name == "yahoo":
        from .yahoo import YahooProvider

        cache = Path(os.environ.get("MONEY_CACHE_DIR", Path.home() / ".cache" / "money"))
        return YahooProvider(cache)
    raise ValueError(f"unknown data provider: {name!r}")
