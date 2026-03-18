#!/bin/bash
# Show active markets closing soonest
# Usage: ./closing_soon.sh [limit]

LIMIT="${1:-25}"

polymarket events list --active true --order volume --limit 200 -o json 2>/dev/null \
  | jq -r --argjson limit "$LIMIT" '
    [ .[] | select(.endDate != null and .endDate != "") ] |
    sort_by(.endDate) | .[:$limit] |
    .[] | "\(.title)\t\(.endDate | split("T")[0])\t$\((.volume // "0") | tonumber | round)"
  ' \
  | awk -F'\t' 'BEGIN {printf "%-60s %12s %15s\n", "Event", "Closes", "Volume"; printf "%-60s %12s %15s\n", "---", "---", "---"} {printf "%-60s %12s %15s\n", $1, $2, $3}'
