"""
Discover and parse Polymarket up/down markets.
Uses the Gamma API directly for structured data.
"""
import subprocess
import json
import re
from datetime import datetime


def fetch_updown_markets(min_liquidity=5000, coin_filter=None):
    """
    Fetch active up/down markets from Polymarket.
    Returns list of parsed market dicts.
    """
    result = subprocess.run(
        ["polymarket", "events", "list", "--active", "true", "--order", "volume",
         "--limit", "200", "-o", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error fetching markets: {result.stderr}")
        return []

    events = json.loads(result.stdout)
    markets = []
    for event in events:
        title = event.get("title", "")
        if "Up or Down" not in title:
            continue
        liquidity = float(event.get("liquidity", 0))
        if liquidity < min_liquidity:
            continue
        if coin_filter and coin_filter.lower() not in title.lower():
            continue

        parsed = parse_market_title(title)
        if parsed:
            parsed["slug"] = event.get("slug", "")
            parsed["liquidity"] = liquidity
            parsed["volume"] = float(event.get("volume", 0))
            parsed["end_date"] = event.get("endDate", "")
            parsed["markets"] = event.get("markets", [])
            markets.append(parsed)

    return markets


def parse_market_title(title):
    """
    Parse 'Bitcoin Up or Down - March 18, 6:15AM-6:30AM ET'
    Returns dict with coin, date, start_time, end_time, timeframe.
    """
    # Match: "Coin Up or Down - Month Day, StartTime-EndTime ET"
    pattern = r"(\w+) Up or Down - (\w+ \d+), (\d+(?::\d+)?(?:AM|PM))-(\d+(?::\d+)?(?:AM|PM)) ET"
    # Also match hour-only format: "10AM ET" with no end time range in title
    pattern2 = r"(\w+) Up or Down - (\w+ \d+), (\d+(?::\d+)?(?:AM|PM)) ET"

    m = re.match(pattern, title)
    if m:
        coin = m.group(1).lower()
        date_str = m.group(2)
        start_time = m.group(3)
        end_time = m.group(4)

        # Calculate timeframe from start/end
        timeframe = _calc_timeframe(start_time, end_time)
        return {
            "coin": coin,
            "date_str": date_str,
            "start_time": start_time,
            "end_time": end_time,
            "timeframe": timeframe,
            "title": title,
        }

    m = re.match(pattern2, title)
    if m:
        coin = m.group(1).lower()
        date_str = m.group(2)
        start_time = m.group(3)
        return {
            "coin": coin,
            "date_str": date_str,
            "start_time": start_time,
            "end_time": None,
            "timeframe": "1h",  # hour-only markets are typically 1h
            "title": title,
        }

    return None


def _calc_timeframe(start, end):
    """Estimate timeframe from start/end time strings."""
    try:
        fmt = "%I:%M%p" if ":" in start else "%I%p"
        fmt2 = "%I:%M%p" if ":" in end else "%I%p"
        t1 = datetime.strptime(start, fmt)
        t2 = datetime.strptime(end, fmt2)
        diff = (t2 - t1).seconds // 60
        if diff <= 5:
            return "5m"
        elif diff <= 15:
            return "15m"
        elif diff <= 60:
            return "1h"
        return f"{diff}m"
    except ValueError:
        return "5m"


def get_market_tokens(market):
    """
    Extract token IDs for UP and DOWN from a market's sub-markets.
    Returns (up_token_id, down_token_id) or (None, None).
    """
    sub_markets = market.get("markets", [])
    up_token = None
    down_token = None
    for sm in sub_markets:
        outcome = (sm.get("groupItemTitle") or sm.get("outcome", "")).lower()
        tokens = sm.get("clobTokenIds")
        if tokens:
            if "up" in outcome:
                up_token = tokens[0] if isinstance(tokens, list) else tokens
            elif "down" in outcome:
                down_token = tokens[0] if isinstance(tokens, list) else tokens
    return up_token, down_token
