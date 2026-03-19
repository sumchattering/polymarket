#!/usr/bin/env python3
"""
Fast vectorized backtester for all strategies.
Auto-discovers strategies from strategies/ directory.

Usage:
    python backtesting/backtest_filtered.py                              # all strategies, 90d, doge+xrp
    python backtesting/backtest_filtered.py --strategy momentum_v4       # single strategy
    python backtesting/backtest_filtered.py --days 30 --coins doge       # custom
    python backtesting/backtest_filtered.py --dynamic                    # 2/3/4% sizing ladder
"""
import sys
import os
import glob
import sqlite3
import argparse
import time
import importlib.util
import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "candles.db")
STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "strategies")
COIN_FULL = {"doge": "dogecoin", "xrp": "xrp", "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "bnb"}


# ── Indicators (vectorized) ─────────────────────────────────────────────

def calc_fee(shares, price):
    return shares * price * 0.25 * (price * (1 - price)) ** 2

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    return 100 - (100 / (1 + gain / loss))

def calc_adx(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    plus_dm = h.diff(); minus_dm = -l.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr = pd.DataFrame({"hl": h-l, "hc": (h-c.shift()).abs(), "lc": (l-c.shift()).abs()}).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(period).mean()

def calc_chop(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.DataFrame({"hl": h-l, "hc": (h-c.shift()).abs(), "lc": (l-c.shift()).abs()}).max(axis=1)
    atr_sum = tr.rolling(period).sum()
    return 100 * np.log10(atr_sum / (h.rolling(period).max() - l.rolling(period).min())) / np.log10(period)

def calc_atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.DataFrame({"hl": h-l, "hc": (h-c.shift()).abs(), "lc": (l-c.shift()).abs()}).max(axis=1)
    return tr.rolling(period).mean()


# ── Data ─────────────────────────────────────────────────────────────────

def load_candles(coin, days=None):
    conn = sqlite3.connect(DB_PATH)
    if days:
        cutoff = int((time.time() - days * 86400) * 1000)
        df = pd.read_sql_query(
            "SELECT * FROM candles_1m WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp",
            conn, params=(coin, cutoff))
    else:
        df = pd.read_sql_query(
            "SELECT * FROM candles_1m WHERE symbol = ? ORDER BY timestamp", conn, params=(coin,))
    conn.close()
    return df

def build_5m_windows(df_1m):
    df_1m = df_1m.copy()
    df_1m["window"] = (df_1m["timestamp"] // 300000) * 300000
    w = df_1m.groupby("window").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum"), count=("open","count")).reset_index()
    w = w[w["count"] == 5].copy()
    w["went_up"] = w["close"] >= w["open"]
    return w

def prepare_data(coin, days):
    """Load candles, compute indicators, merge to 5m windows."""
    df_1m = load_candles(coin, days)
    if df_1m.empty:
        return None
    df_5m = build_5m_windows(df_1m)
    df_1m = df_1m.copy()

    # Compute all indicators we might need
    for p in [7, 10, 14, 21, 28]:
        df_1m[f"rsi_{p}"] = calc_rsi(df_1m["close"], p)
    df_1m["adx_14"] = calc_adx(df_1m, 14)
    df_1m["chop_14"] = calc_chop(df_1m, 14)
    df_1m["atr_14"] = calc_atr(df_1m, 14)
    df_1m["ema_20"] = df_1m["close"].ewm(span=20, adjust=False).mean()
    df_1m["stretch_atr_20"] = (df_1m["close"] - df_1m["ema_20"]) / df_1m["atr_14"]

    # Consec5: 5 consecutive candles same direction
    candle_up = (df_1m["close"] > df_1m["open"]).astype(int)
    candle_down = (df_1m["close"] < df_1m["open"]).astype(int)
    df_1m["consec5_up"] = candle_up.rolling(5).sum() == 5
    df_1m["consec5_down"] = candle_down.rolling(5).sum() == 5

    # Merge: get last 1m candle before each 5m window
    df_5m_s = df_5m.sort_values("window").copy()
    df_5m_s["lookup_ts"] = df_5m_s["window"] - 60000

    ind_cols = ["timestamp"] + [f"rsi_{p}" for p in [7,10,14,21,28]] + [
        "adx_14", "chop_14", "atr_14", "ema_20", "stretch_atr_20", "consec5_up", "consec5_down"
    ]
    m = pd.merge_asof(
        df_5m_s[["window", "went_up", "lookup_ts"]],
        df_1m.sort_values("timestamp")[ind_cols],
        left_on="lookup_ts", right_on="timestamp", direction="backward")
    m["hour"] = pd.to_datetime(m["window"], unit="ms").dt.hour
    m["month"] = pd.to_datetime(m["window"], unit="ms").dt.strftime("%Y-%m")
    return m


# ── Strategy configs ─────────────────────────────────────────────────────
# Each strategy is defined by its signal + filter params.
# We read from files but map to vectorized configs.

STRATEGY_PARAMS = {
    "momentum_v2": {"rsi_col": "rsi_14", "rsi_lo": 30, "rsi_hi": 70, "adx": 25, "chop": 50,
                     "consec5": True, "skip_hours": {},
                     "desc": "Consec5+RSI(14) 30/70 + ADX/CHOP"},
    "momentum_v3": {"rsi_col": "rsi_14", "rsi_lo": 30, "rsi_hi": 70, "adx": 25, "chop": 50,
                     "consec5": False, "skip_hours": {},
                     "desc": "RSI(14) 30/70 + ADX/CHOP"},
    "momentum_v4": {"rsi_col": "rsi_21", "rsi_lo": 35, "rsi_hi": 65, "adx": 25, "chop": 50,
                     "consec5": False, "skip_hours": {},
                     "desc": "RSI(21) 35/65 + ADX/CHOP"},
    "momentum_v5": {"rsi_col": "rsi_21", "rsi_lo": 35, "rsi_hi": 65, "adx": 25, "chop": 50,
                     "consec5": False,
                     "skip_hours": {"dogecoin": {6,10,14}, "xrp": {3,5,8,9,10,14}},
                     "desc": "RSI(21) 35/65 + ADX/CHOP + time filter"},
}


def get_strategy_params(name):
    """Get params for a known strategy, or None."""
    return STRATEGY_PARAMS.get(name)


def discover_strategies():
    """Find all strategy files."""
    strats = {}
    for path in sorted(glob.glob(os.path.join(STRATEGIES_DIR, "*.py"))):
        name = os.path.basename(path).replace(".py", "")
        if name.startswith("__"):
            continue
        strats[name] = path
    return strats


# ── Vectorized evaluation ────────────────────────────────────────────────

def _resolve_params(params, coin_full):
    overrides = params.get("coin_overrides", {}).get(coin_full)
    if overrides:
        params = {**params, **overrides}
    return params


def _build_single_masks(m, params, coin_full):
    """Build a single pair of UP/DOWN masks from one strategy config."""
    params = _resolve_params(params, coin_full)

    filt = pd.Series(True, index=m.index)

    adx_min = params.get("adx")
    if adx_min is not None:
        filt = filt & (m["adx_14"] > adx_min)

    adx_max = params.get("adx_max")
    if adx_max is not None:
        filt = filt & (m["adx_14"] < adx_max)

    chop_max = params.get("chop")
    if chop_max is not None:
        filt = filt & (m["chop_14"] < chop_max)

    chop_min = params.get("chop_min")
    if chop_min is not None:
        filt = filt & (m["chop_14"] > chop_min)

    skip = params.get("skip_hours", {})
    if isinstance(skip, dict):
        skip = skip.get(coin_full, set())
    if skip:
        filt = filt & (~m["hour"].isin(skip))

    rsi_col = params["rsi_col"]
    stretch_col = params.get("stretch_col", "stretch_atr_20")
    min_stretch = params.get("min_stretch_atr")

    stretch_up = pd.Series(True, index=m.index)
    stretch_down = pd.Series(True, index=m.index)
    if min_stretch is not None:
        stretch_up = m[stretch_col] <= -min_stretch
        stretch_down = m[stretch_col] >= min_stretch

    if params.get("consec5"):
        # Consec5 has priority, RSI fills in when no consec signal
        consec_up = filt & m["consec5_up"]
        consec_down = filt & m["consec5_down"]
        rsi_up = filt & (m[rsi_col] < params["rsi_lo"]) & stretch_up & ~consec_up & ~consec_down
        rsi_down = filt & (m[rsi_col] > params["rsi_hi"]) & stretch_down & ~consec_up & ~consec_down
        up_mask = consec_up | rsi_up
        down_mask = consec_down | rsi_down
    else:
        up_mask = filt & (m[rsi_col] < params["rsi_lo"]) & stretch_up
        down_mask = filt & (m[rsi_col] > params["rsi_hi"]) & stretch_down

    return up_mask, down_mask


def _build_signal_masks(m, params, coin_full):
    """Build UP/DOWN signal masks from strategy params. Returns (up_mask, down_mask)."""
    up_mask, down_mask = _build_single_masks(m, params, coin_full)

    for extra in params.get("extra_entries", []):
        coins = extra.get("coins")
        if coins and coin_full not in coins:
            continue

        extra_up, extra_down = _build_single_masks(m, extra, coin_full)
        if extra.get("only_when_base_absent", True):
            extra_up = extra_up & ~up_mask & ~down_mask
            extra_down = extra_down & ~up_mask & ~down_mask

        up_mask = up_mask | extra_up
        down_mask = down_mask | extra_down

    return up_mask, down_mask


def eval_fast(m, params, coin_full):
    """Evaluate strategy on merged dataframe using vectorized ops. Returns stats dict."""
    up_mask, down_mask = _build_signal_masks(m, params, coin_full)

    total = int(up_mask.sum() + down_mask.sum())
    if total == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0}

    wins = int(m[up_mask]["went_up"].sum() + (~m[down_mask]["went_up"]).sum())
    return {"trades": total, "wins": wins, "losses": total - wins, "wr": wins / total * 100}


def simulate_pnl(m, params, coin_full, initial_balance=100.0, bet_size=5.0, dynamic_sizing=False):
    """Simulate with balance tracking."""
    up_mask, down_mask = _build_signal_masks(m, params, coin_full)

    signal = pd.Series(0, index=m.index)
    signal[up_mask] = 1
    signal[down_mask] = -1
    trades = m[signal != 0].copy()
    trades["signal"] = signal[signal != 0].values
    trades["won"] = ((trades["signal"] == 1) & trades["went_up"]) | \
                    ((trades["signal"] == -1) & ~trades["went_up"])

    balance = initial_balance
    peak = initial_balance
    min_bal = initial_balance
    wins = losses = 0

    for won in trades["won"].values:
        if dynamic_sizing:
            if balance >= 400: bs = balance * 0.04
            elif balance >= 200: bs = balance * 0.03
            else: bs = balance * 0.02
        else:
            bs = bet_size
        bs = min(bs, balance)
        if bs < 0.50:
            break

        if won:
            shares = bs / 0.505
            fee = calc_fee(shares, 0.505)
            balance += shares - bs - fee
            wins += 1
        else:
            balance -= bs
            losses += 1

        balance = max(balance, 0)
        peak = max(peak, balance)
        min_bal = min(min_bal, balance)

    total = wins + losses
    days_span = (m["window"].max() - m["window"].min()) / 86400000
    return {
        "trades": total, "wins": wins, "losses": losses,
        "wr": (wins / total * 100) if total > 0 else 0,
        "pnl": balance - initial_balance, "final": balance,
        "min_bal": min_bal, "peak": peak,
        "max_dd_pct": ((peak - min_bal) / peak * 100) if peak > 0 else 0,
        "trades_per_day": total / max(days_span, 1),
    }


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--coins", nargs="+", default=["doge", "xrp"])
    parser.add_argument("--strategy", default=None, help="e.g. momentum_v4, or omit for all")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--bet", type=float, default=5.0)
    parser.add_argument("--dynamic", action="store_true", help="2%%/3%%/4%% sizing ladder")
    args = parser.parse_args()

    available = discover_strategies()
    if args.strategy:
        if args.strategy not in available:
            print(f"Not found: {args.strategy}. Available: {', '.join(available.keys())}")
            return
        strats = {args.strategy: available[args.strategy]}
    else:
        strats = available

    sizing = "2%→3%→4% ladder" if args.dynamic else f"flat ${args.bet}"
    print(f"Backtesting | {args.days} days | ${args.balance} start | {sizing}")
    print(f"Coins: {', '.join(args.coins)} | Strategies: {', '.join(strats.keys())}")
    print()

    for coin in args.coins:
        t0 = time.time()
        m = prepare_data(coin, args.days)
        if m is None:
            print(f"  {coin}: no data"); continue
        days_actual = (m["window"].max() - m["window"].min()) / 86400000
        coin_full = COIN_FULL.get(coin, coin)
        print(f"{'=' * 105}")
        print(f"  {coin.upper()} — {len(m):,} windows, {days_actual:.0f} days (loaded in {time.time()-t0:.1f}s)")
        print(f"{'=' * 105}")
        print(f"  {'Strategy':<20} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'Tr/Day':>7} {'PnL':>9} {'Final$':>8} {'Min$':>7} {'DD%':>5}")
        print(f"  {'-' * 85}")

        for name in strats:
            params = get_strategy_params(name)
            if not params:
                print(f"  {name:<20} — no vectorized params defined, skipping")
                continue

            # WR from full eval (not affected by balance busting)
            e = eval_fast(m, params, coin_full)
            # PnL from sequential simulation
            r = simulate_pnl(m, params, coin_full, args.balance, args.bet, args.dynamic)
            if e["trades"] == 0:
                print(f"  {name:<20} — no trades —"); continue

            tpd = e["trades"] / max(days_actual, 1)
            star = " ***" if e["wr"] > 50.8 else ""
            print(f"  {name:<20} {e['trades']:>6} {e['wins']:>5} {e['wr']:>5.1f}% "
                  f"{tpd:>6.1f} ${r['pnl']:>+8.0f} ${r['final']:>7.0f} "
                  f"${r['min_bal']:>6.0f} {r['max_dd_pct']:>4.0f}%{star}")

        # Monthly breakdown for all strategies
        print()
        for name in strats:
            params = get_strategy_params(name)
            if not params: continue
            print(f"  {name} monthly:")
            for month, grp in m.groupby("month"):
                r = eval_fast(grp, params, coin_full)
                if r["trades"] > 0:
                    print(f"    {month}: {r['trades']:>5} trades, {r['wr']:.1f}% WR")
        print()


if __name__ == "__main__":
    main()
