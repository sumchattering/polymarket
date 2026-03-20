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
STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "..", "strategies")
COIN_FULL = {"doge": "dogecoin", "xrp": "xrp", "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "bnb"}

TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000, "4h": 14_400_000}


# -- Indicators (vectorized) ------------------------------------------------

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


# -- Data -------------------------------------------------------------------

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

def build_windows(df_1m, window_ms=300_000):
    """Build market windows of specified size from 1m candles."""
    df = df_1m.copy()
    candles_per_window = window_ms // 60_000
    df["window"] = (df["timestamp"] // window_ms) * window_ms
    w = df.groupby("window").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum"), count=("open","count")).reset_index()
    w = w[w["count"] == candles_per_window].copy()
    w["went_up"] = w["close"] >= w["open"]
    return w

def aggregate_candles(df_1m, candle_mins=5):
    """Aggregate 1m candles into larger candles (e.g. 5m)."""
    df = df_1m.copy()
    agg_ms = candle_mins * 60_000
    df["agg_window"] = (df["timestamp"] // agg_ms) * agg_ms
    agg = df.groupby("agg_window").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum"), count=("open","count")).reset_index()
    agg = agg[agg["count"] == candle_mins].copy()
    agg = agg.rename(columns={"agg_window": "timestamp"})
    return agg

def compute_indicators(df):
    """Compute all indicators on a candle DataFrame."""
    df = df.copy()
    for p in [7, 10, 14, 21, 28]:
        df[f"rsi_{p}"] = calc_rsi(df["close"], p)
    df["adx_14"] = calc_adx(df, 14)
    df["chop_14"] = calc_chop(df, 14)
    df["atr_14"] = calc_atr(df, 14)
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["stretch_atr_20"] = (df["close"] - df["ema_20"]) / df["atr_14"]

    candle_up = (df["close"] > df["open"]).astype(int)
    candle_down = (df["close"] < df["open"]).astype(int)
    df["consec5_up"] = candle_up.rolling(5).sum() == 5
    df["consec5_down"] = candle_down.rolling(5).sum() == 5
    return df

def merge_indicators_to_windows(df_windows, df_ind, candle_ms=60_000):
    """Merge indicator values (last candle before window) to market windows."""
    df_ws = df_windows.sort_values("window").copy()
    df_ws["lookup_ts"] = df_ws["window"] - candle_ms

    ind_cols = ["timestamp"] + [f"rsi_{p}" for p in [7,10,14,21,28]] + [
        "adx_14", "chop_14", "atr_14", "ema_20", "stretch_atr_20", "consec5_up", "consec5_down"
    ]
    m = pd.merge_asof(
        df_ws[["window", "went_up", "lookup_ts"]],
        df_ind.sort_values("timestamp")[ind_cols],
        left_on="lookup_ts", right_on="timestamp", direction="backward")
    m["hour"] = pd.to_datetime(m["window"], unit="ms").dt.hour
    m["month"] = pd.to_datetime(m["window"], unit="ms").dt.strftime("%Y-%m")
    return m

def prepare_data(coin, days, timeframe="5m", indicator_candle_mins=1):
    """Load candles, compute indicators, merge to market windows."""
    df_1m = load_candles(coin, days)
    if df_1m.empty:
        return None

    window_ms = TIMEFRAME_MS[timeframe]
    df_windows = build_windows(df_1m, window_ms)

    # Build indicator candles (1m or aggregated)
    if indicator_candle_mins == 1:
        df_ind = compute_indicators(df_1m)
        candle_ms = 60_000
    else:
        df_agg = aggregate_candles(df_1m, indicator_candle_mins)
        df_ind = compute_indicators(df_agg)
        candle_ms = indicator_candle_mins * 60_000

    return merge_indicators_to_windows(df_windows, df_ind, candle_ms)


# -- Strategy configs -------------------------------------------------------

STRATEGY_PARAMS = {
    "momentum_v2": {
        "rsi_col": "rsi_14", "rsi_lo": 30, "rsi_hi": 70, "adx": 25, "chop": 50,
        "consec5": True, "skip_hours": {}, "timeframe": "5m",
        "desc": "Consec5+RSI(14) 30/70 + ADX/CHOP"},
    "momentum_v3": {
        "rsi_col": "rsi_14", "rsi_lo": 30, "rsi_hi": 70, "adx": 25, "chop": 50,
        "consec5": False, "skip_hours": {}, "timeframe": "5m",
        "desc": "RSI(14) 30/70 + ADX/CHOP"},
    "momentum_v4": {
        "rsi_col": "rsi_21", "rsi_lo": 35, "rsi_hi": 65, "adx": 25, "chop": 50,
        "consec5": False, "skip_hours": {}, "timeframe": "5m",
        "desc": "RSI(21) 35/65 + ADX/CHOP"},
    "momentum_v5": {
        "rsi_col": "rsi_21", "rsi_lo": 35, "rsi_hi": 65, "adx": 25, "chop": 50,
        "consec5": False, "timeframe": "5m",
        "skip_hours": {"dogecoin": {6,10,14}, "xrp": {3,5,8,9,10,14}},
        "desc": "RSI(21) 35/65 + ADX/CHOP + time filter"},
    "momentum_v4_15m": {
        "rsi_col": "rsi_21", "rsi_lo": 35, "rsi_hi": 65, "adx": 25, "chop": 50,
        "consec5": False, "skip_hours": {}, "timeframe": "15m",
        "desc": "RSI(21) 35/65 + ADX/CHOP [15m]"},
    "momentum_v4_candle5": {
        "rsi_col": "rsi_21", "rsi_lo": 35, "rsi_hi": 65, "adx": 25, "chop": 50,
        "consec5": False, "skip_hours": {}, "timeframe": "15m", "indicator_candle_mins": 5,
        "desc": "RSI(21) 35/65 + ADX/CHOP on 5m candles [15m]"},
}


def get_strategy_params(name):
    return STRATEGY_PARAMS.get(name)


def discover_strategies():
    strats = {}
    for path in sorted(glob.glob(os.path.join(STRATEGIES_DIR, "*.py"))):
        name = os.path.basename(path).replace(".py", "")
        if name.startswith("__"):
            continue
        strats[name] = path
    return strats


# -- Vectorized evaluation --------------------------------------------------

def _resolve_params(params, coin_full):
    overrides = params.get("coin_overrides", {}).get(coin_full)
    if overrides:
        params = {**params, **overrides}
    return params


def _build_single_masks(m, params, coin_full):
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
    up_mask, down_mask = _build_signal_masks(m, params, coin_full)

    total = int(up_mask.sum() + down_mask.sum())
    if total == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0}

    wins = int(m[up_mask]["went_up"].sum() + (~m[down_mask]["went_up"]).sum())
    return {"trades": total, "wins": wins, "losses": total - wins, "wr": wins / total * 100}


def simulate_pnl(m, params, coin_full, initial_balance=100.0, bet_size=5.0, dynamic_sizing=False):
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


# -- Expected WR cache ------------------------------------------------------

EXPECTED_WR_PATH = os.path.join(os.path.dirname(__file__), "expected_wr.json")

def cache_expected_wrs(days=90):
    """Compute expected WRs and trades/day for all strategy+coin combos and save to JSON."""
    import json
    all_coins = list(COIN_FULL.keys())
    strat_names = list(STRATEGY_PARAMS.keys())
    data_cache = {}
    results = {}

    for coin in all_coins:
        coin_full = COIN_FULL[coin]
        for name in strat_names:
            params = STRATEGY_PARAMS[name]
            tf = params.get("timeframe", "5m")
            ind_mins = params.get("indicator_candle_mins", 1)
            cache_key = (coin, tf, ind_mins)

            if cache_key not in data_cache:
                m = prepare_data(coin, days, timeframe=tf, indicator_candle_mins=ind_mins)
                if m is not None:
                    days_span = (m["window"].max() - m["window"].min()) / 86400000
                    data_cache[cache_key] = (m, max(days_span, 1))
                else:
                    data_cache[cache_key] = (None, 0)

            m, days_span = data_cache[cache_key]
            if m is None:
                continue

            e = eval_fast(m, params, coin_full)
            if e["trades"] > 0:
                key = f"{name}_{coin_full}"
                results[key] = {
                    "wr": round(e["wr"], 1),
                    "trades_per_day": round(e["trades"] / days_span, 1),
                }

    with open(EXPECTED_WR_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Cached expected stats for {len(results)} strategy+coin combos -> {EXPECTED_WR_PATH}")
    return results


def load_expected_wrs():
    """Load cached expected WRs. Returns dict or empty dict."""
    import json
    try:
        with open(EXPECTED_WR_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# -- Main -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--coins", nargs="+", default=["doge", "xrp"])
    parser.add_argument("--strategy", default=None, help="e.g. momentum_v4, or omit for all")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--bet", type=float, default=5.0)
    parser.add_argument("--dynamic", action="store_true", help="2%%/3%%/4%% sizing ladder")
    parser.add_argument("--cache-expected", action="store_true", help="Pre-compute expected WRs for fronttester")
    args = parser.parse_args()

    if args.cache_expected:
        cache_expected_wrs(args.days)
        return

    available = discover_strategies()
    if args.strategy:
        if args.strategy not in available:
            print(f"Not found: {args.strategy}. Available: {', '.join(available.keys())}")
            return
        strats = {args.strategy: available[args.strategy]}
    else:
        strats = available

    # Only include strategies that have vectorized params
    strat_names = [n for n in strats if get_strategy_params(n)]
    if not strat_names:
        print("No strategies with backtest params found.")
        return

    sizing = "2%->3%->4% ladder" if args.dynamic else f"flat ${args.bet}"
    print(f"Backtesting | {args.days} days | ${args.balance} start | {sizing}")
    print(f"Coins: {', '.join(args.coins)} | Strategies: {', '.join(strat_names)}")
    print()

    # Cache prepared data by (coin, timeframe, indicator_candle_mins)
    data_cache = {}

    for coin in args.coins:
        coin_full = COIN_FULL.get(coin, coin)
        print(f"{'=' * 105}")
        print(f"  {coin.upper()}")
        print(f"{'=' * 105}")
        print(f"  {'Strategy':<25} {'TF':>3} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'Tr/Day':>7} {'PnL':>9} {'Final$':>8} {'Min$':>7} {'DD%':>5}")
        print(f"  {'-' * 95}")

        for name in strat_names:
            params = get_strategy_params(name)
            tf = params.get("timeframe", "5m")
            ind_mins = params.get("indicator_candle_mins", 1)
            cache_key = (coin, tf, ind_mins)

            if cache_key not in data_cache:
                t0 = time.time()
                m = prepare_data(coin, args.days, timeframe=tf, indicator_candle_mins=ind_mins)
                if m is not None:
                    days_actual = (m["window"].max() - m["window"].min()) / 86400000
                    data_cache[cache_key] = (m, days_actual)
                else:
                    data_cache[cache_key] = (None, 0)

            m, days_actual = data_cache[cache_key]
            if m is None:
                print(f"  {name:<25} {tf:>3} — no data —")
                continue

            e = eval_fast(m, params, coin_full)
            r = simulate_pnl(m, params, coin_full, args.balance, args.bet, args.dynamic)
            if e["trades"] == 0:
                print(f"  {name:<25} {tf:>3} — no trades —")
                continue

            tpd = e["trades"] / max(days_actual, 1)
            star = " ***" if e["wr"] > 50.8 else ""
            print(f"  {name:<25} {tf:>3} {e['trades']:>6} {e['wins']:>5} {e['wr']:>5.1f}% "
                  f"{tpd:>6.1f} ${r['pnl']:>+8.0f} ${r['final']:>7.0f} "
                  f"${r['min_bal']:>6.0f} {r['max_dd_pct']:>4.0f}%{star}")

        # Monthly breakdown
        print()
        for name in strat_names:
            params = get_strategy_params(name)
            tf = params.get("timeframe", "5m")
            ind_mins = params.get("indicator_candle_mins", 1)
            cache_key = (coin, tf, ind_mins)
            m, _ = data_cache.get(cache_key, (None, 0))
            if m is None: continue
            print(f"  {name} monthly:")
            for month, grp in m.groupby("month"):
                r = eval_fast(grp, params, coin_full)
                if r["trades"] > 0:
                    print(f"    {month}: {r['trades']:>5} trades, {r['wr']:.1f}% WR")
        print()

    # Auto-save expected WRs for all coins (not just displayed ones)
    cache_expected_wrs(args.days)


if __name__ == "__main__":
    main()
