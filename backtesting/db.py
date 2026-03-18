"""
SQLite database for backtesting simulation.
Acts as a simulated Polymarket account with transactional accounting.
"""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "polymarket_simulation.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    initial_balance REAL NOT NULL,
    balance REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    market_slug TEXT NOT NULL,
    coin TEXT NOT NULL,
    timeframe TEXT NOT NULL,          -- '5m' or '1h'
    direction TEXT NOT NULL,          -- 'UP' or 'DOWN'
    confidence REAL NOT NULL,
    entry_price REAL NOT NULL,        -- price paid per share (e.g. 0.50)
    bet_size_usd REAL NOT NULL,
    shares REAL NOT NULL,
    outcome TEXT DEFAULT 'PENDING',   -- 'WIN', 'LOSS', 'PENDING'
    pnl REAL DEFAULT 0.0,
    fees REAL DEFAULT 0.0,
    start_price REAL,                 -- BTC price at market open
    end_price REAL,                   -- BTC price at market close
    placed_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    balance REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    total_trades INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    total_pnl REAL NOT NULL
);
"""


def get_db(db_path=None):
    """Get a database connection with WAL mode for concurrent reads."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(initial_balance=100.0, db_path=None):
    """Initialize database schema and account with starting balance."""
    conn = get_db(db_path)
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat()
    # Insert account if not exists
    existing = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO account (id, initial_balance, balance, created_at, updated_at) VALUES (1, ?, ?, ?, ?)",
            (initial_balance, initial_balance, now, now),
        )
        conn.commit()
        print(f"Account initialized with ${initial_balance:.2f}")
    else:
        row = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
        print(f"Account exists with ${row['balance']:.2f}")
    conn.close()


def get_balance(db_path=None):
    """Get current account balance."""
    conn = get_db(db_path)
    row = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
    conn.close()
    return row["balance"] if row else 0.0


def get_open_positions(db_path=None):
    """Get count of pending trades."""
    conn = get_db(db_path)
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM trades WHERE outcome = 'PENDING'"
    ).fetchone()
    conn.close()
    return row["cnt"]


def place_bet(strategy, market_slug, coin, timeframe, direction, confidence,
              entry_price, bet_size_usd, start_price, db_path=None):
    """
    Place a simulated bet. Deducts bet_size from balance immediately.
    Returns trade_id or None if insufficient balance.
    """
    conn = get_db(db_path)
    try:
        balance = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()["balance"]
        if balance < bet_size_usd:
            print(f"Insufficient balance: ${balance:.2f} < ${bet_size_usd:.2f}")
            return None

        shares = bet_size_usd / entry_price
        now = datetime.now(timezone.utc).isoformat()

        # Transactional: deduct balance and insert trade
        conn.execute(
            "UPDATE account SET balance = balance - ?, updated_at = ? WHERE id = 1",
            (bet_size_usd, now),
        )
        cursor = conn.execute(
            """INSERT INTO trades
               (strategy, market_slug, coin, timeframe, direction, confidence,
                entry_price, bet_size_usd, shares, start_price, placed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (strategy, market_slug, coin, timeframe, direction, confidence,
             entry_price, bet_size_usd, shares, start_price, now),
        )
        trade_id = cursor.lastrowid
        conn.commit()
        print(f"Placed {direction} bet #{trade_id}: ${bet_size_usd:.2f} @ {entry_price} on {coin} ({strategy})")
        return trade_id
    finally:
        conn.close()


def resolve_trade(trade_id, outcome, end_price, fee_rate=0.10, db_path=None):
    """
    Resolve a trade as WIN or LOSS.
    WIN: credit shares * 1.0 minus fee on profit.
    LOSS: nothing returned (already deducted).
    """
    conn = get_db(db_path)
    try:
        trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not trade:
            print(f"Trade #{trade_id} not found")
            return
        if trade["outcome"] != "PENDING":
            print(f"Trade #{trade_id} already resolved as {trade['outcome']}")
            return

        now = datetime.now(timezone.utc).isoformat()
        bet_size = trade["bet_size_usd"]
        shares = trade["shares"]

        if outcome == "WIN":
            gross_payout = shares * 1.0  # Each share pays $1 on win
            profit = gross_payout - bet_size
            fees = profit * fee_rate
            net_payout = gross_payout - fees
            pnl = net_payout - bet_size

            # Credit winnings back to account
            conn.execute(
                "UPDATE account SET balance = balance + ?, updated_at = ? WHERE id = 1",
                (net_payout, now),
            )
        else:  # LOSS
            pnl = -bet_size
            fees = 0.0

        conn.execute(
            """UPDATE trades SET outcome = ?, pnl = ?, fees = ?,
               end_price = ?, resolved_at = ? WHERE id = ?""",
            (outcome, pnl, fees, end_price, now, trade_id),
        )
        conn.commit()
        balance = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()["balance"]
        print(f"Trade #{trade_id} → {outcome} | PnL: ${pnl:+.2f} | Balance: ${balance:.2f}")
    finally:
        conn.close()


def get_stats(strategy=None, db_path=None):
    """Get trading statistics, optionally filtered by strategy."""
    conn = get_db(db_path)
    where = "WHERE outcome != 'PENDING'"
    params = []
    if strategy:
        where += " AND strategy = ?"
        params.append(strategy)

    trades = conn.execute(f"SELECT * FROM trades {where}", params).fetchall()
    balance = get_balance(db_path)
    open_pos = get_open_positions(db_path)

    total = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    total_pnl = sum(t["pnl"] for t in trades)
    total_fees = sum(t["fees"] for t in trades)

    conn.close()
    return {
        "balance": balance,
        "open_positions": open_pos,
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / total * 100) if total > 0 else 0,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
    }


def take_snapshot(db_path=None):
    """Save a point-in-time snapshot of account state."""
    stats = get_stats(db_path=db_path)
    conn = get_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO account_snapshots
           (timestamp, balance, open_positions, total_trades, wins, losses, total_pnl)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (now, stats["balance"], stats["open_positions"], stats["total_trades"],
         stats["wins"], stats["losses"], stats["total_pnl"]),
    )
    conn.commit()
    conn.close()


def reset_account(initial_balance=100.0, db_path=None):
    """Reset the simulation — wipes all trades and resets balance."""
    conn = get_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM trades")
    conn.execute("DELETE FROM account_snapshots")
    conn.execute(
        "UPDATE account SET balance = ?, initial_balance = ?, updated_at = ? WHERE id = 1",
        (initial_balance, initial_balance, now),
    )
    conn.commit()
    conn.close()
    print(f"Account reset to ${initial_balance:.2f}")
