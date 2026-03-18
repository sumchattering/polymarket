#!/bin/bash
# Show trending markets — searches popular categories and ranks by 24hr volume
# Usage: ./trending.sh [limit]

LIMIT="${1:-25}"

# Fetch active events from popular search terms and merge
(
  polymarket markets search "bitcoin" --limit 50 -o json 2>/dev/null
  polymarket markets search "ethereum" --limit 50 -o json 2>/dev/null
  polymarket markets search "trump" --limit 50 -o json 2>/dev/null
  polymarket markets search "election" --limit 50 -o json 2>/dev/null
  polymarket markets search "fed" --limit 50 -o json 2>/dev/null
  polymarket markets search "recession" --limit 50 -o json 2>/dev/null
  polymarket markets search "war" --limit 50 -o json 2>/dev/null
) | jq -r -s --argjson limit "$LIMIT" '
  [ .[][] | select(.active == true) ] |
  unique_by(.id) |
  [ .[] | .vol24 = ((.volume24hr // "0") | tonumber) ] |
  sort_by(-.vol24) | .[:$limit] |
  .[] | "\(.question)\t$\(.vol24 | round)\t$\((.volume // "0") | tonumber | round)"
' | awk -F'\t' 'BEGIN {printf "%-70s %15s %15s\n", "Market", "24hr Volume", "Total Volume"; printf "%-70s %15s %15s\n", "---", "---", "---"} {printf "%-70s %15s %15s\n", substr($1,1,70), $2, $3}'
