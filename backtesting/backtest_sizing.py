#!/usr/bin/env python3
"""
Test dynamic position sizing strategies on Consec5 OR RSI 30/70 + ADX/CHOP filter.
"""
import sys
import os
import sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from backtest_filtered import load_candles, build_5m_windows, generate_signals, calc_fee

COINS = ["doge", "xrp"]
DAYS = 30
INITIAL = 100.0


def simulate(signals, df_5m, sizing_fn, label):
    """Run simulation with a custom sizing function."""
    balance = INITIAL
    peak = INITIAL
    min_balance = INITIAL
    wins = 0
    losses = 0
    max_bet = 0
    balances = []

    for direction, idx, reason, adx_val, chop_val in signals:
        bet_size = sizing_fn(balance, wins, losses)
        bet_size = min(bet_size, balance)  # can't bet more than we have
        bet_size = round(bet_size, 2)

        if bet_size < 0.50:  # minimum bet
            continue

        max_bet = max(max_bet, bet_size)
        went_up = df_5m.iloc[idx]["went_up"]
        won = (direction == "UP") == went_up

        if won:
            shares = bet_size / 0.505
            fee = calc_fee(shares, 0.505)
            pnl = (shares * 1.0) - bet_size - fee
            wins += 1
        else:
            pnl = -bet_size
            losses += 1

        balance += pnl
        balance = max(balance, 0)
        peak = max(peak, balance)
        min_balance = min(min_balance, balance)
        balances.append(balance)

        if balance < 0.50:
            break

    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    max_dd = ((peak - min_balance) / peak * 100) if peak > 0 else 0

    return {
        "label": label,
        "trades": total,
        "wr": wr,
        "final": balance,
        "pnl": balance - INITIAL,
        "min_bal": min_balance,
        "max_dd_pct": max_dd,
        "peak": peak,
        "max_bet": max_bet,
        "busted": balance < 0.50,
    }


def main():
    sizing_strategies = {
        # Fixed $5 (baseline)
        "Fixed $5": lambda bal, w, l: 5.0,

        # Fixed % of balance
        "2% of balance": lambda bal, w, l: bal * 0.02,
        "3% of balance": lambda bal, w, l: bal * 0.03,
        "5% of balance": lambda bal, w, l: bal * 0.05,
        "7% of balance": lambda bal, w, l: bal * 0.07,
        "10% of balance": lambda bal, w, l: bal * 0.10,

        # Kelly criterion: f* = (bp - q) / b where b=payout odds, p=win prob, q=lose prob
        # For 50.5c entry, win pays ~0.98:1, so b≈0.98
        # With ~55% WR: f* = (0.98*0.55 - 0.45) / 0.98 = 0.089 = 8.9%
        # Half-Kelly is safer
        "Quarter Kelly (~2.2%)": lambda bal, w, l: bal * 0.022,
        "Half Kelly (~4.5%)": lambda bal, w, l: bal * 0.045,
        "Full Kelly (~9%)": lambda bal, w, l: bal * 0.09,

        # Scaled: start small, increase as profits grow
        "Scale 2-5% (2%+profit*3%)": lambda bal, w, l: bal * (0.02 + max(0, (bal - INITIAL) / bal) * 0.03),
        "Scale 2-8% (2%+profit*6%)": lambda bal, w, l: bal * (0.02 + max(0, (bal - INITIAL) / bal) * 0.06),

        # Floor: % of balance but never less than $1
        "3% floor $1": lambda bal, w, l: max(1.0, bal * 0.03),
        "5% floor $1": lambda bal, w, l: max(1.0, bal * 0.05),

        # Cap: % but capped to limit risk
        "5% cap $25": lambda bal, w, l: min(25.0, bal * 0.05),
        "5% cap $50": lambda bal, w, l: min(50.0, bal * 0.05),
    }

    for coin in COINS:
        print(f"\n{'='*100}")
        print(f"  {coin.upper()} — Consec5 OR RSI 30/70 + ADX>25 & CHOP<50 — 30 days, $100 start")
        print(f"{'='*100}")

        df_1m = load_candles(coin, DAYS)
        df_5m = build_5m_windows(df_1m)
        signals, _ = generate_signals(df_1m, df_5m, filter_mode="both")

        print(f"  Total signals: {len(signals)}")
        print()
        print(f"  {'SIZING':<28} {'TRADES':>6} {'WR%':>6} {'FINAL$':>9} {'PnL':>9} {'MIN$':>8} {'PEAK$':>8} {'DD%':>5} {'MaxBet':>7} {'BUST':>5}")
        print(f"  {'-'*92}")

        results = []
        for label, fn in sizing_strategies.items():
            r = simulate(signals, df_5m, fn, label)
            results.append(r)

        # Sort by final balance descending
        results.sort(key=lambda r: r["final"], reverse=True)

        for r in results:
            bust_str = "BUST" if r["busted"] else ""
            star = "***" if r["final"] > INITIAL and r["max_dd_pct"] < 50 else ""
            print(
                f"  {r['label']:<28} {r['trades']:>6} {r['wr']:>5.1f}% "
                f"${r['final']:>8.0f} ${r['pnl']:>+8.0f} ${r['min_bal']:>7.0f} ${r['peak']:>7.0f} "
                f"{r['max_dd_pct']:>4.0f}% ${r['max_bet']:>6.1f} {bust_str:>5} {star}"
            )

        # Highlight best risk-adjusted
        safe = [r for r in results if r["max_dd_pct"] < 50 and r["trades"] > 100 and not r["busted"]]
        if safe:
            best = max(safe, key=lambda r: r["pnl"])
            print(f"\n  BEST (DD < 50%): {best['label']} — ${best['pnl']:+.0f} PnL, {best['max_dd_pct']:.0f}% DD, {best['trades']} trades")

        profitable = [r for r in results if not r["busted"] and r["pnl"] > 0]
        if profitable:
            best_overall = max(profitable, key=lambda r: r["pnl"] / max(r["max_dd_pct"], 1))
            print(f"  BEST RISK-ADJ:   {best_overall['label']} — ${best_overall['pnl']:+.0f} PnL, {best_overall['max_dd_pct']:.0f}% DD (PnL/DD ratio: {best_overall['pnl']/max(best_overall['max_dd_pct'],1):.1f})")


if __name__ == "__main__":
    main()
