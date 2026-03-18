# Session Log — March 18, 2026

## What We Did

### 1. Project Setup
- Initialized git repo at `/Users/sumeru.chatterjee/MyProjects/polymarket`
- Created README.md
- Pushed to `git@github.com:sumchattering/polymarket.git` (SSH — HTTPS didn't work due to credential mismatch)

### 2. Installed Polymarket CLI
- `brew tap Polymarket/polymarket-cli` + `brew install polymarket`
- Version: 0.1.4 (reports as 0.1.0)
- Ran `polymarket setup` — created a new wallet (user's Gmail-based Polymarket account is separate/custodial, can't export private key)

### 3. Wallet Details
- **CLI Wallet**: `0xdE6B45eCA7C95bC3718c7C445bf2755cF7aF3E19`
- **Proxy Wallet** (deposit address): `0xef76825478B9114Df71e4202b68a01C4E26EA072`
- Config: `/Users/sumeru.chatterjee/.config/polymarket/config.json`
- Signature type: proxy, Chain ID: 137 (Polygon)
- Balance: $0.00 (unfunded)
- The Gmail account (`samlearnstorock@gmail.com`, wallet `0xaF22Fc...`) is a separate custodial account — NOT used by CLI

### 4. Project Structure
```
polymarket/
├── .env                 # Wallet address, proxy address, config path
├── .gitignore           # Ignores .env
├── README.md
├── account/
│   ├── balance.sh       # polymarket clob balance --asset-type collateral
│   ├── status.sh        # polymarket clob account-status
│   └── wallet.sh        # polymarket wallet show
├── interesting/
│   ├── search.sh        # Search markets by keyword (implemented)
│   ├── bitcoin.sh       # Bitcoin price prediction markets (implemented)
│   ├── updown.sh        # Up/Down 5min+1hr markets with min liquidity filter (implemented)
│   ├── trending.sh      # Trending by 24hr volume (implemented, searches popular categories)
│   ├── top_volume.sh    # Top by total volume (implemented)
│   ├── top_liquidity.sh # Top by liquidity (implemented)
│   ├── tags.sh          # Browse by tag (implemented)
│   └── closing_soon.sh  # Markets closing soonest (implemented)
└── strategies/
    └── ARCHITECTURE.md  # Full system design document
```

### 5. CLI Quirks Discovered
- Polymarket API only sorts ascending — no descending option
- `volume_num` is not a valid sort field, use `volume`
- `end_date_iso` not a valid sort field for events
- Market search returns `liquidityNum` as 0 — liquidity is on event level
- Workaround: fetch JSON, sort client-side with jq
- `--ascending` flag doesn't seem to change behavior (API defaults to ascending regardless)

### 6. Up/Down Markets
- 5-minute markets resolve via Chainlink data streams
- 1-hour markets resolve via Binance candle data
- All times are ET (Eastern Time)
- User's local timezone: WET (4 hours ahead of ET)
- These are the primary markets of interest for the trading strategy

### 7. Trading System Architecture
- Designed full architecture for automated Up/Down market trading (see strategies/ARCHITECTURE.md)
- User has existing code/API for order block detection — will provide it
- Decision: user will provide the ORDER BLOCK CODE directly (not API) — better for backtesting speed
- Language: Python with py-clob-client SDK
- Storage: SQLite
- Single async process for live trading

## Funding Note
- Wallet is unfunded ($0.00). User considered buying USDC via MetaMask.
- Cheapest deposit routes: Base or Polygon ($2 min), Solana ($2 min)
- This was deferred — will need to be done before live trading.

## Next Steps
1. User will provide order block detection code
2. Scaffold the strategies/ folder structure
3. Implement data pipeline (ccxt → Binance → SQLite cache)
4. Implement backtester
5. Implement live trader
6. Fund wallet with USDC before going live
