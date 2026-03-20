# Going Live Plan

## Overview

Transition from front-testing (simulated trades) to live trading (real USDC) on Polymarket's crypto Up/Down markets. The system architecture: a Hetzner server runs trading bots 24/7, a mobile app provides wallet backup and manual control.

## Prerequisites (before any real trades)

### 1. Front-test validation (in progress)
- [ ] 8-day front-test completes for all strategies
- [ ] 400+ trades per strategy/coin combo
- [ ] Win rate above 54% sustained
- [ ] Profitable every 2-day stretch
- [ ] Select best strategy per coin for go-live

### 2. Polygon wallets
- [ ] Generate one EOA wallet per coin (6 total: DOGE, XRP, SOL, BNB, BTC, ETH)
- [ ] Store private keys in `config-wallet-{coin}.json` files
- [ ] Fund each wallet with a small amount of POL (~0.1 POL) for approval txs
- [ ] Fund each wallet with starting USDC.e capital

### 3. On-chain approvals (one-time per wallet)
Each wallet needs 6 approval transactions to let Polymarket's contracts spend USDC and conditional tokens:

**Tokens to approve:**
- USDC.e: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
- Conditional Tokens (CTF): `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`

**Approve both tokens for these 3 contracts:**
| Contract | Address |
|----------|---------|
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` |
| Neg Risk CTF Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` |
| Neg Risk Adapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` |

Script reference: https://gist.github.com/poly-rodr/44313920481de58d5a3f6d1f8226bd5e

### 4. Install Python SDK
```bash
pip install py-clob-client
```

## Architecture

```
┌─────────────────────────────────────┐
│  Hetzner Server                     │
│                                     │
│  /root/keys/config-wallet-*.json    │  ← chmod 600, root only
│                                     │
│  trader user runs:                  │
│    • Trading bot per coin           │
│    • Each bot: strategy → signal    │
│      → CLOB order → track result    │
│                                     │
│  SSH: key-only + root password      │
│  Firewall: port 22 only            │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  iPhone App (backup + monitor)      │
│                                     │
│  • Same private keys, encrypted     │
│    with password + FaceID gate      │
│  • View balances (public key only)  │
│  • Send USDC (decrypt → sign → tx) │
└─────────────────────────────────────┘
```

## Polymarket CLOB API

### Authentication
Two levels:
- **L1**: Sign EIP-712 message with private key (proves wallet ownership)
- **L2**: API key/secret/passphrase (derived from L1, used for all trading calls)

The Python SDK handles both automatically.

### Placing orders

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# Initialize
client = ClobClient(
    host="https://clob.polymarket.com",
    key="<PRIVATE_KEY>",
    chain_id=137,
    signature_type=0,              # EOA wallet
    funder="<WALLET_ADDRESS>"
)

# Derive API creds (once per session)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# Market order (FOK — fill or kill)
resp = client.create_and_post_market_order(
    MarketOrderArgs(token_id="<up_token>", amount=5.0, side=BUY),
    options={"tickSize": "0.01", "negRisk": True},
    order_type=OrderType.FOK
)

# Limit order (GTC — good til cancelled)
resp = client.create_and_post_order(
    OrderArgs(token_id="<up_token>", price=0.55, size=10.0, side=BUY),
    options={"tickSize": "0.01", "negRisk": True},
    order_type=OrderType.GTC
)
```

### Order types
| Type | Use case |
|------|----------|
| **FOK** (Fill-Or-Kill) | Market orders — fill immediately or cancel entirely |
| **GTC** (Good-Til-Cancelled) | Limit orders — rest on book until filled |
| **GTD** (Good-Til-Date) | Limit with expiry — auto-cancel at timestamp |

### Order signing
All orders are signed locally with your private key (EIP-712). The key never leaves your machine. The SDK handles signing automatically.

### Fees
- Crypto markets: `fee = shares * price * 0.25 * (price * (1-price))^2`
- Max ~1.56% at p=0.50 (where Up/Down markets trade)
- Our simulation already uses this exact formula — no surprises going live

### Rate limits
- POST /order: 3,500 per 10s (we do ~1 per 5 minutes)
- Market data: 1,500 per 10s (we do ~1 per 5 minutes)
- Not a concern at all

### Token IDs
Already handled by our `market.py` — it extracts `up_token` and `down_token` from the Gamma API response. These are the `tokenID` values passed to the CLOB.

## Code changes for live trading

### What stays the same
- Strategy signal generation (strategies/*.py)
- Market discovery (market.py — Gamma API)
- Price data (price.py — Binance/ccxt)
- Position sizing logic

### What changes
- **run_live.py** `place_bet_fast()` → instead of writing to simulation DB, call CLOB API
- **db.py** → still tracks trades locally, but also records real order IDs
- **resolve_pending()** → check actual market resolution + real P&L
- **New**: wallet management module (load keys, init CLOB client per wallet)

### Suggested approach
1. Add a `--live` flag to `run_live.py`
2. When `--live`: use CLOB API to place real orders, still track in local DB
3. When not `--live`: current simulation behavior (for continued testing)
4. Same strategy code, same signals — just a different execution backend

## Deployment phases

### Phase 1: $200 on 5m (day 1)
- $100 DOGE + $100 XRP on 5-minute markets
- Best strategy per coin from front-test
- Separate wallet per coin

### Phase 2: Deploy on 15m (week 2-3)
- Once 5m bets hit liquidity limits, deploy new capital on 15m
- Start with highest WR coins from front-test

### Phase 3: All markets (month 2+)
- Spread across all 6 coins on 15m
- Total ceiling: ~$41k across all markets

### Liquidity caps (balance where 4% bet = ~10% of market liquidity)
| Market | Max Bet | Balance at Cap |
|--------|---------|---------------|
| 5m DOGE | $100 | $2,500 |
| 5m XRP | $140 | $3,500 |
| 15m DOGE | $160 | $4,000 |
| 15m XRP | $200 | $5,000 |
| 15m SOL | $220 | $5,500 |
| 15m ETH | $260 | $6,500 |
| 15m BTC | $400 | $10,000 |
| 15m BNB | $160 | $4,000 |

## Server setup checklist

- [ ] Provision Hetzner VPS (cheapest tier is fine)
- [ ] SSH key-only login, root password for su
- [ ] Firewall: allow port 22 only
- [ ] Create `trader` user for running bots
- [ ] Clone repo, set up Python venv
- [ ] Place wallet key files in /root/keys/ (chmod 600)
- [ ] Run approval transactions for each wallet
- [ ] Deploy trading bots as systemd services
- [ ] Set up monitoring/alerts (balance drops, bot crashes)

## Mobile app checklist

- [ ] Generate keys or import from server
- [ ] Encrypt private keys with user password
- [ ] FaceID gate before password entry
- [ ] View balances screen (public key only, query Polygon RPC)
- [ ] Send USDC screen (decrypt key → sign tx → broadcast → wipe key)
- [ ] Simple, minimal — no dApp browser, no swaps, no NFTs
