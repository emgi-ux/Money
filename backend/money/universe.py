"""Built-in stock universes.

Sectors follow GICS naming so that sector-neutral scoring groups peers sensibly.
Custom universes can always be passed as a plain list of tickers.
"""

from __future__ import annotations

# Large-cap US equities (roughly the S&P 100), grouped by GICS sector.
US_LARGE_CAP: dict[str, str] = {
    # Information Technology
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "NVDA": "Information Technology", "AVGO": "Information Technology",
    "ORCL": "Information Technology", "CRM": "Information Technology",
    "ADBE": "Information Technology", "AMD": "Information Technology",
    "CSCO": "Information Technology", "ACN": "Information Technology",
    "INTC": "Information Technology", "IBM": "Information Technology",
    "QCOM": "Information Technology", "TXN": "Information Technology",
    "INTU": "Information Technology", "NOW": "Information Technology",
    "AMAT": "Information Technology", "MU": "Information Technology",
    # Communication Services
    "GOOGL": "Communication Services", "META": "Communication Services",
    "NFLX": "Communication Services", "DIS": "Communication Services",
    "CMCSA": "Communication Services", "T": "Communication Services",
    "VZ": "Communication Services", "TMUS": "Communication Services",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "LOW": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary", "BKNG": "Consumer Discretionary",
    "TJX": "Consumer Discretionary", "GM": "Consumer Discretionary",
    # Consumer Staples
    "WMT": "Consumer Staples", "PG": "Consumer Staples",
    "COST": "Consumer Staples", "KO": "Consumer Staples",
    "PEP": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "MDLZ": "Consumer Staples",
    "CL": "Consumer Staples",
    # Health Care
    "LLY": "Health Care", "UNH": "Health Care", "JNJ": "Health Care",
    "ABBV": "Health Care", "MRK": "Health Care", "TMO": "Health Care",
    "ABT": "Health Care", "PFE": "Health Care", "DHR": "Health Care",
    "AMGN": "Health Care", "BMY": "Health Care", "GILD": "Health Care",
    "CVS": "Health Care", "MDT": "Health Care", "ISRG": "Health Care",
    # Financials
    "BRK-B": "Financials", "JPM": "Financials", "V": "Financials",
    "MA": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials", "AXP": "Financials",
    "BLK": "Financials", "C": "Financials", "SCHW": "Financials",
    "USB": "Financials", "PYPL": "Financials", "COF": "Financials",
    # Industrials
    "GE": "Industrials", "CAT": "Industrials", "HON": "Industrials",
    "UNP": "Industrials", "RTX": "Industrials", "BA": "Industrials",
    "LMT": "Industrials", "DE": "Industrials", "UPS": "Industrials",
    "MMM": "Industrials", "GD": "Industrials", "FDX": "Industrials",
    "EMR": "Industrials",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    # Real Estate
    "AMT": "Real Estate", "PLD": "Real Estate", "SPG": "Real Estate",
    # Materials
    "LIN": "Materials", "DOW": "Materials",
}

UNIVERSES: dict[str, dict[str, str]] = {
    "us_large_cap": US_LARGE_CAP,
}

DEFAULT_UNIVERSE = "us_large_cap"
DEFAULT_BENCHMARK = "SPY"


def resolve_universe(name_or_tickers: str | list[str] | None) -> list[str]:
    """Turn a universe name, comma-separated string or list into tickers."""
    if name_or_tickers is None:
        return list(UNIVERSES[DEFAULT_UNIVERSE])
    if isinstance(name_or_tickers, list):
        return [t.strip().upper() for t in name_or_tickers if t.strip()]
    if name_or_tickers in UNIVERSES:
        return list(UNIVERSES[name_or_tickers])
    return [t.strip().upper() for t in name_or_tickers.split(",") if t.strip()]


def known_sector(ticker: str) -> str | None:
    for members in UNIVERSES.values():
        if ticker in members:
            return members[ticker]
    return None
