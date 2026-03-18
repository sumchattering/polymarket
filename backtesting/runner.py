"""
Backtesting runner — executes a strategy against live or historical markets.

Can run as:
  - One-shot: evaluate current markets and place bets
  - Cron: run every N minutes to catch new 5-min markets
  - Resolve: check pending bets and resolve them
"""
import sys
import os
import time
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import db
import config
import price
import market


def run_strategy(strategy_fn, strategy_name="default", coin="bitcoin", timeframe="5m"):
    """
    Run one cycle: find markets, generate signals, place bets.
    strategy_fn(coin, timeframe, current_price, ohlcv) -> (direction, confidence) or None
    """
    # Check constraints
    balance = db.get_balance()
    open_pos = db.get_open_positions()

    if balance < config.MIN_BET_SIZE:
        print(f"Balance too low: ${balance:.2f}")
        return

    if open_pos >= config.MAX_CONCURRENT_BETS:
        print(f"Max concurrent bets reached: {open_pos}")
        return

    # Get current Bitcoin price
    symbol = price.symbol_for_coin(coin)
    current_price = price.get_current_price(symbol)
    print(f"Current {coin} price: ${current_price:,.2f}")

    # Get recent OHLCV for strategy analysis
    ohlcv = price.get_ohlcv(symbol, "1m", limit=60)

    # Run the strategy
    result = strategy_fn(coin, timeframe, current_price, ohlcv)
    if result is None:
        print("Strategy says SKIP")
        return

    direction, confidence = result

    if confidence < config.MIN_CONFIDENCE:
        print(f"Confidence {confidence:.2f} below threshold {config.MIN_CONFIDENCE}")
        return

    # Position sizing (simple for now — can add Kelly later)
    bet_size = min(config.DEFAULT_BET_SIZE, balance)

    # Find a matching market to bet on
    markets = market.fetch_updown_markets(
        min_liquidity=config.MIN_LIQUIDITY, coin_filter=coin
    )
    five_min_markets = [m for m in markets if m["timeframe"] == timeframe]

    if not five_min_markets:
        print(f"No active {timeframe} {coin} markets found")
        return

    # Pick the next upcoming market (first one by start time)
    target = five_min_markets[0]
    print(f"Target market: {target['title']}")

    # Place the simulated bet
    trade_id = db.place_bet(
        strategy=strategy_name,
        market_slug=target.get("slug", target["title"]),
        coin=coin,
        timeframe=timeframe,
        direction=direction,
        confidence=confidence,
        entry_price=config.DEFAULT_ENTRY_PRICE,
        bet_size_usd=bet_size,
        start_price=current_price,
    )

    return trade_id


def resolve_pending(coin="bitcoin"):
    """
    Check all pending trades and resolve them by comparing prices.
    For 5-min markets: check if 5 minutes have passed since placement.
    """
    conn = db.get_db()
    pending = conn.execute(
        "SELECT * FROM trades WHERE outcome = 'PENDING' AND coin = ?",
        (coin,)
    ).fetchall()
    conn.close()

    if not pending:
        print("No pending trades to resolve")
        return

    symbol = price.symbol_for_coin(coin)
    current_price = price.get_current_price(symbol)

    for trade in pending:
        placed_at = datetime.fromisoformat(trade["placed_at"])
        now = datetime.now(timezone.utc)
        elapsed_min = (now - placed_at).total_seconds() / 60

        # Resolve based on timeframe
        timeframe_min = {"5m": 5, "15m": 15, "1h": 60}.get(trade["timeframe"], 5)

        if elapsed_min < timeframe_min:
            remaining = timeframe_min - elapsed_min
            print(f"Trade #{trade['id']}: {remaining:.1f}min remaining")
            continue

        # Determine outcome
        start_price = trade["start_price"]
        went_up = current_price >= start_price

        if (trade["direction"] == "UP" and went_up) or \
           (trade["direction"] == "DOWN" and not went_up):
            outcome = "WIN"
        else:
            outcome = "LOSS"

        db.resolve_trade(trade["id"], outcome, current_price, config.FEE_RATE)

    # Take a snapshot after resolving
    db.take_snapshot()


def show_stats(strategy=None):
    """Print current stats."""
    stats = db.get_stats(strategy=strategy)
    print(f"\n{'='*40}")
    print(f"  Balance:       ${stats['balance']:.2f}")
    print(f"  Open Positions: {stats['open_positions']}")
    print(f"  Total Trades:   {stats['total_trades']}")
    print(f"  Wins:           {stats['wins']}")
    print(f"  Losses:         {stats['losses']}")
    print(f"  Win Rate:       {stats['win_rate']:.1f}%")
    print(f"  Total PnL:     ${stats['total_pnl']:+.2f}")
    print(f"  Total Fees:    ${stats['total_fees']:.2f}")
    print(f"{'='*40}\n")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Backtesting Runner")
    parser.add_argument("action", choices=["init", "bet", "resolve", "stats", "reset"],
                        help="Action to perform")
    parser.add_argument("--strategy", default="random_test",
                        help="Strategy name to use")
    parser.add_argument("--coin", default="bitcoin")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--balance", type=float, default=100.0,
                        help="Initial balance for init/reset")
    args = parser.parse_args()

    if args.action == "init":
        db.init_db(args.balance)
        show_stats()

    elif args.action == "bet":
        # Import strategy dynamically
        strategy_fn = _load_strategy(args.strategy)
        run_strategy(strategy_fn, args.strategy, args.coin, args.timeframe)
        show_stats()

    elif args.action == "resolve":
        resolve_pending(args.coin)
        show_stats()

    elif args.action == "stats":
        show_stats(args.strategy if args.strategy != "random_test" else None)

    elif args.action == "reset":
        db.reset_account(args.balance)
        show_stats()


def _load_strategy(name):
    """Load a strategy function from backtesting/strategies/<name>.py"""
    import importlib.util
    strategy_path = os.path.join(os.path.dirname(__file__), "strategies", f"{name}.py")
    if not os.path.exists(strategy_path):
        print(f"Strategy file not found: {strategy_path}")
        print("Using random test strategy")
        return _random_strategy

    spec = importlib.util.spec_from_file_location(name, strategy_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_signal


def _random_strategy(coin, timeframe, current_price, ohlcv):
    """Simple random strategy for testing the infrastructure."""
    import random
    direction = random.choice(["UP", "DOWN"])
    confidence = random.uniform(0.5, 0.9)
    return direction, confidence


if __name__ == "__main__":
    main()
