#!/bin/bash
# Find active "Up or Down" short-term crypto markets with minimum liquidity
# Usage: ./updown.sh              — show all with >= $5000 liquidity
#        ./updown.sh 10000        — custom min liquidity
#        ./updown.sh 5000 bitcoin — filter by coin

MIN_LIQ="${1:-5000}"
COIN_FILTER="${2:-}"

polymarket events list --active true --order volume --limit 200 -o json 2>/dev/null \
  | jq -r --argjson min "$MIN_LIQ" --arg coin "$COIN_FILTER" '
    [ .[] |
      select(.title | test("Up or Down")) |
      select((.liquidity // "0") | tonumber >= $min) |
      if $coin != "" then select(.title | test($coin; "i")) else . end
    ] |
    sort_by(-(.liquidity | tonumber)) |
    .[] | "\(.title)\t$\((.liquidity // "0") | tonumber | round)\t$\((.volume // "0") | tonumber | round)\t\(.endDate | split("T")[0])"
  ' \
  | awk -F'\t' 'BEGIN {printf "%-55s %12s %12s %12s\n", "Market", "Liquidity", "Volume", "Closes"; printf "%-55s %12s %12s %12s\n", "---", "---", "---", "---"} {printf "%-55s %12s %12s %12s\n", substr($1,1,55), $2, $3, $4}'
