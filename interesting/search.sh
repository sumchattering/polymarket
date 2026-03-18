#!/bin/bash
# Search for markets by keyword
# Usage: ./search.sh "bitcoin price"
#        ./search.sh "election" 20

QUERY="${1:?Usage: ./search.sh <query> [limit]}"
LIMIT="${2:-10}"

polymarket markets search "$QUERY" --limit "$LIMIT"
