#!/usr/bin/env bash

set -e

MESSAGE_FILE="$1"

if [ -z "$MESSAGE_FILE" ] || [ ! -f "$MESSAGE_FILE" ]; then
  echo "Commit message file not found."
  exit 1
fi

MESSAGE="$(head -n 1 "$MESSAGE_FILE")"

PATTERN='^(feat|fix|docs|style|refactor|build|ci|test|chore)\([a-z0-9-]+\): .+'

if ! printf '%s\n' "$MESSAGE" | grep -Eq "$PATTERN"; then
  echo
  echo "Invalid commit message:"
  echo
  echo "  $MESSAGE"
  echo
  echo "Expected Conventional Commit format:"
  echo
  echo "  <type>(<scope>): <description>"
  echo
  echo "Allowed types:"
  echo "  feat      New functionality"
  echo "  fix       Bug fix"
  echo "  docs      Documentation only"
  echo "  style     Formatting only, no behavior changes"
  echo "  refactor  Code change without a feature or bug fix"
  echo "  build     Build system or build integration"
  echo "  ci        CI and verification pipeline"
  echo "  test      Tests or test infrastructure"
  echo "  chore     Repository maintenance"
  echo
  echo "Scopes:"
  echo "  Use the module slug for module-specific changes:"
  echo "    npc-teleport"
  echo "    npc-transmogrifier"
  echo
  echo "  Use 'repo' for repository-wide changes."
  echo
  echo "Examples:"
  echo "  feat(npc-teleport): add SkyFire 5.4.8 port"
  echo "  fix(npc-transmogrifier): correct gossip routing"
  echo "  docs(npc-teleport): document upstream source"
  echo "  style(npc-transmogrifier): apply C++ formatting"
  echo "  ci(repo): add module verification workflow"
  echo "  chore(repo): add Lefthook formatting and commit checks"
  echo
  exit 1
fi

exit 0
