#!/bin/bash
# Show markets with highest total trading volume
# Uses search across popular categories to find high-volume markets
# Usage: ./top_volume.sh [limit]

LIMIT="${1:-25}"

(
  polymarket markets search "bitcoin" --limit 50 -o json 2>/dev/null
  polymarket markets search "ethereum" --limit 50 -o json 2>/dev/null
  polymarket markets search "trump" --limit 50 -o json 2>/dev/null
  polymarket markets search "election" --limit 50 -o json 2>/dev/null
  polymarket markets search "recession" --limit 50 -o json 2>/dev/null
  polymarket markets search "price" --limit 50 -o json 2>/dev/null
) | jq -r -s --argjson limit "$LIMIT" '
  [ .[][] | select(.active == true) ] |
  unique_by(.id) |
  [ .[] | .vol = ((.volume // "0") | tonumber) | .liq = ((.liquidity // "0") | tonumber) ] |
  sort_by(-.vol) | .[:$limit] |
  .[] | "\(.question)\t$\(.vol | round)\t$\(.liq | round)"
' | awk -F'\t' 'BEGIN {printf "%-70s %15s %15s\n", "Market", "Volume", "Liquidity"; printf "%-70s %15s %15s\n", "---", "---", "---"} {printf "%-70s %15s %15s\n", substr($1,1,70), $2, $3}'
