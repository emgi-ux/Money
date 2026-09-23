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
    """Build a provider by name: "synthetic", "yahoo" (personal use) or "fmp" (licensable).

    Defaults to the ``MONEY_PROVIDER`` environment variable, else "synthetic".
    """
    name = (name or os.environ.get("MONEY_PROVIDER") or "synthetic").lower()
    if name == "synthetic":
        return SyntheticProvider()
    if name == "yahoo":
        from .yahoo import YahooProvider

        cache = Path(os.environ.get("MONEY_CACHE_DIR", Path.home() / ".cache" / "money"))
        return YahooProvider(cache)
    if name == "fmp":
        from .fmp import FMPProvider

        cache = Path(os.environ.get("MONEY_CACHE_DIR", Path.home() / ".cache" / "money"))
        return FMPProvider(os.environ.get("FMP_API_KEY", ""), cache)
    raise ValueError(f"unknown data provider: {name!r}")
