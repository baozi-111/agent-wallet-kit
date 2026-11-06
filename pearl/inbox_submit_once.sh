#!/usr/bin/env bash
# One pass over the inbox. Does not broadcast unless you add --execute.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
INBOX="${PEARL_INBOX:-}"
if [[ $# -gt 0 && "$1" != --* ]]; then
  INBOX="$1"
  shift
fi
if [[ -z "$INBOX" ]]; then
  INBOX="${PEARL_STATE_DIR:-$PWD/pearl-state}/inbox"
fi
exec python3 "$ROOT/submit_ff.py" --inbox "$INBOX" --once "$@"
