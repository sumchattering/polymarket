#!/bin/bash
# Show markets with highest liquidity (deepest order books)
# Usage: ./top_liquidity.sh [limit]

LIMIT="${1:-25}"

polymarket events list --active true --order volume --limit 200 -o json 2>/dev/null \
  | jq -r --argjson limit "$LIMIT" '
    [ .[] | .vol = ((.volume // "0") | tonumber) | .liq = ((.liquidity // "0") | tonumber) ] |
    sort_by(-.liq) | .[:$limit] |
    .[] | "\(.title)\t$\(.liq | round)\t$\(.vol | round)"
  ' \
  | awk -F'\t' 'BEGIN {printf "%-60s %15s %15s\n", "Event", "Liquidity", "Volume"; printf "%-60s %15s %15s\n", "---", "---", "---"} {printf "%-60s %15s %15s\n", $1, $2, $3}'
