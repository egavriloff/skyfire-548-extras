#!/usr/bin/env bash

set -e

MESSAGE="$(head -n 1 "$1")"

PATTERN='^(feat|fix|docs|refactor|build|ci|chore|test)(\([a-z0-9-]+\))?: .+'

if ! printf '%s\n' "$MESSAGE" | grep -Eq "$PATTERN"; then
    echo "Invalid commit message:"
    echo
    echo "  $MESSAGE"
    echo
    echo "Expected Conventional Commit format:"
    echo
    echo "  feat(npc-teleport): add SkyFire 5.4.8 port"
    echo "  fix(npc-transmogrifier): correct gossip routing"
    echo "  docs(repo): update installation guide"
    echo
    exit 1
fi
