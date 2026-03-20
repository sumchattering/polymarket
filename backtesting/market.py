"""
Polymarket up/down market discovery.
Uses the Gamma API and the slug timestamp pattern to find markets.
"""
import json
import re
import time
import requests
from datetime import datetime, timezone


GAMMA_API = "https://gamma-api.polymarket.com"


# Timeframe configs: name -> (seconds, slug_suffix)
TIMEFRAMES = {
    "5m":  (300,  "5m"),
    "15m": (900,  "15m"),
    "4h":  (14400, "4h"),
}


def get_current_market(coin="btc", timeframe="5m"):
    """Get the currently active market for any timeframe."""
    secs, slug_tf = TIMEFRAMES[timeframe]
    now = int(time.time())
    window_start = (now // secs) * secs
    slug = f"{coin}-updown-{slug_tf}-{window_start}"
    return _fetch_market_by_slug(slug, window_start, secs)


def get_next_market(coin="btc", timeframe="5m"):
    """Get the next upcoming market."""
    secs, slug_tf = TIMEFRAMES[timeframe]
    now = int(time.time())
    next_window = ((now // secs) + 1) * secs
    slug = f"{coin}-updown-{slug_tf}-{next_window}"
    return _fetch_market_by_slug(slug, next_window, secs)


def get_market_at(coin="btc", timestamp=None, timeframe="5m"):
    """Get the market for a specific timestamp."""
    secs, slug_tf = TIMEFRAMES[timeframe]
    window_start = (timestamp // secs) * secs
    slug = f"{coin}-updown-{slug_tf}-{window_start}"
    return _fetch_market_by_slug(slug, window_start, secs)


# Backwards compatible aliases
def get_current_5m_market(coin="btc"):
    return get_current_market(coin, "5m")

def get_next_5m_market(coin="btc"):
    return get_next_market(coin, "5m")


def _fetch_market_by_slug(slug, window_start, window_secs=300):
    """Fetch market data from Gamma API by slug."""
    url = f"{GAMMA_API}/events?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None

    if not data:
        return None

    event = data[0]
    sub_markets = event.get("markets", [])
    if not sub_markets:
        return None

    sm = sub_markets[0]

    # Parse outcome prices
    up_price = 0.50
    down_price = 0.50
    try:
        prices = json.loads(sm.get("outcomePrices", "[]"))
        if len(prices) >= 2:
            up_price = float(prices[0])
            down_price = float(prices[1])
    except (json.JSONDecodeError, ValueError):
        pass

    best_bid = float(sm.get("bestBid", 0) or 0)
    best_ask = float(sm.get("bestAsk", 0) or 0)

    # Parse token IDs
    up_token = None
    down_token = None
    try:
        tokens = json.loads(sm.get("clobTokenIds", "[]"))
        if len(tokens) >= 2:
            up_token = tokens[0]
            down_token = tokens[1]
    except (json.JSONDecodeError, ValueError):
        pass

    window_end = window_start + window_secs
    now = int(time.time())
    elapsed = now - window_start
    remaining = max(0, window_end - now)

    return {
        "title": event.get("title", ""),
        "slug": slug,
        "event_id": event.get("id"),
        "market_id": sm.get("id"),
        "condition_id": sm.get("conditionId"),
        "up_price": up_price,
        "down_price": down_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "up_token": up_token,
        "down_token": down_token,
        "window_start": window_start,
        "window_end": window_end,
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "active": sm.get("active", False),
        "closed": sm.get("closed", False),
    }


def get_market_result(slug):
    """
    Check if a market has resolved and who won.
    Returns: "UP", "DOWN", or None if not yet resolved.
    """
    url = f"{GAMMA_API}/events?slug={slug}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    if not data:
        return None

    event = data[0]
    sub_markets = event.get("markets", [])
    if not sub_markets:
        return None

    sm = sub_markets[0]
    if not sm.get("closed", False):
        return None  # Not resolved yet

    try:
        prices = json.loads(sm.get("outcomePrices", "[]"))
        if len(prices) >= 2:
            up_price = float(prices[0])
            down_price = float(prices[1])
            if up_price > 0.5:
                return "UP"
            elif down_price > 0.5:
                return "DOWN"
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def get_live_odds(coin="btc"):
    """
    Get current live odds for the active 5-minute market.
    Returns a dict with prices and timing info.
    """
    mkt = get_current_5m_market(coin)
    if not mkt:
        return None
    return {
        "title": mkt["title"],
        "up": mkt["up_price"],
        "down": mkt["down_price"],
        "ask": mkt["best_ask"],
        "bid": mkt["best_bid"],
        "elapsed": mkt["elapsed_seconds"],
        "remaining": mkt["remaining_seconds"],
    }
