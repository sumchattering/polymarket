"""
Fetch Bitcoin (and other crypto) prices from Binance via ccxt.
Used to verify whether UP or DOWN bets won.
"""
import ccxt
from datetime import datetime, timezone

_exchange = None


def _get_exchange():
    global _exchange
    if _exchange is None:
        _exchange = ccxt.binance({"enableRateLimit": True})
    return _exchange


def get_current_price(symbol="BTC/USDT"):
    """Get the current price of a symbol."""
    exchange = _get_exchange()
    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"]


def get_price_at(symbol="BTC/USDT", timestamp_ms=None):
    """
    Get the closing price of a 1-minute candle at or near a given timestamp.
    If timestamp_ms is None, returns current price.
    """
    if timestamp_ms is None:
        return get_current_price(symbol)

    exchange = _get_exchange()
    # Fetch the 1m candle that contains this timestamp
    candles = exchange.fetch_ohlcv(symbol, "1m", since=timestamp_ms, limit=1)
    if candles:
        return candles[0][4]  # close price
    return None


def get_ohlcv(symbol="BTC/USDT", timeframe="1m", since=None, limit=100):
    """Fetch OHLCV candles from Binance."""
    exchange = _get_exchange()
    return exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)


def did_price_go_up(symbol="BTC/USDT", start_ms=None, end_ms=None,
                     start_price=None, end_price=None):
    """
    Determine if price went up between two timestamps.
    Can pass prices directly or timestamps to look them up.
    Returns: (went_up: bool, start_price: float, end_price: float)
    """
    if start_price is None:
        start_price = get_price_at(symbol, start_ms)
    if end_price is None:
        end_price = get_price_at(symbol, end_ms)

    return end_price >= start_price, start_price, end_price


# Coin name → Binance symbol mapping
COIN_SYMBOLS = {
    "bitcoin": "BTC/USDT",
    "btc": "BTC/USDT",
    "ethereum": "ETH/USDT",
    "eth": "ETH/USDT",
    "solana": "SOL/USDT",
    "sol": "SOL/USDT",
    "dogecoin": "DOGE/USDT",
    "doge": "DOGE/USDT",
    "xrp": "XRP/USDT",
    "bnb": "BNB/USDT",
}


def symbol_for_coin(coin_name):
    """Map a Polymarket coin name to a Binance symbol."""
    return COIN_SYMBOLS.get(coin_name.lower(), f"{coin_name.upper()}/USDT")
