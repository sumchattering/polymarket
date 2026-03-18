#!/bin/bash
# Browse markets by tag/category
# Usage: ./tags.sh              — list all tags
#        ./tags.sh crypto       — show markets for a specific tag
#        ./tags.sh politics 50  — show markets for a tag with custom limit

TAG="${1:-}"
LIMIT="${2:-25}"

if [ -z "$TAG" ]; then
    echo "=== Available Tags ==="
    polymarket tags list --limit 50
    echo ""
    echo "Usage: ./tags.sh <tag-slug> [limit]"
else
    echo "=== Markets tagged: $TAG ==="
    polymarket events list --active true --tag "$TAG" --limit "$LIMIT"
fi
