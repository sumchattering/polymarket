# Polymarket

Playing with the Polymarket API and ecosystem.

## Structure

- `account/` — Wallet and balance scripts
- `interesting/` — Market discovery scripts (search, up/down, trending, etc.)
- `strategies/` — Automated trading system (see [ARCHITECTURE.md](strategies/ARCHITECTURE.md))

## Setup

```bash
brew tap Polymarket/polymarket-cli https://github.com/Polymarket/polymarket-cli
brew install polymarket
polymarket setup
```

## Quick Start

```bash
# Search markets
./interesting/search.sh "bitcoin price"

# Find up/down 5-min markets with $5K+ liquidity
./interesting/updown.sh 5000

# Filter by coin
./interesting/updown.sh 5000 solana

# Check balance
./account/balance.sh
```
