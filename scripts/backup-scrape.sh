#!/usr/bin/env bash
# Backup scrape trigger — fires a scan if the last scheduled run was missed.
# Designed to run via cron at :30 past each scheduled hour as a safety net.
#
# Usage:
#   ./scripts/backup-scrape.sh                    # uses default URL
#   SCRAPE_URL=http://host:port ./scripts/backup-scrape.sh  # override
#
# Cron example (run at 8:30 AM and 8:30 PM ET):
#   30 8,20 * * * /path/to/scripts/backup-scrape.sh >> /var/log/backup-scrape.log 2>&1

set -euo pipefail

SCRAPE_URL="${SCRAPE_URL:-http://192.168.17.224:8766}"
RESUME_CLI="${RESUME_CLI:-resume-builder}"  # path to CLI binary
WORKSPACE="${WORKSPACE:-}"                   # set to skip auto-discovery
TODAY=$(TZ=America/New_York date +%Y-%m-%d)
POLL_INTERVAL=30                             # seconds between status checks
POLL_TIMEOUT=1800                            # max wait for scan (30 min)

# Get last run timestamp from the API
schedule=$(curl -sf "$SCRAPE_URL/api/scrape-schedule" 2>/dev/null) || {
  echo "$(date -u +%FT%TZ) ERROR: Could not reach $SCRAPE_URL/api/scrape-schedule"
  exit 1
}

last_run=$(echo "$schedule" | python3 -c "import sys,json; print(json.load(sys.stdin)['last_run'])" 2>/dev/null) || {
  echo "$(date -u +%FT%TZ) ERROR: Could not parse last_run from schedule response"
  exit 1
}

# Extract the date portion (handle both UTC and offset timestamps)
last_run_date=$(echo "$last_run" | python3 -c "
import sys
from datetime import datetime, timezone
ts = sys.stdin.read().strip()
# Python 3.7+ fromisoformat doesn't handle 'Z' suffix
ts = ts.replace('Z', '+00:00')
dt = datetime.fromisoformat(ts)
print(dt.strftime('%Y-%m-%d'))
" 2>/dev/null)

if [ "$last_run_date" = "$TODAY" ]; then
  echo "$(date -u +%FT%TZ) OK: Last run was today ($last_run). No action needed."
  exit 0
fi

# Last run was not today — trigger a scan
echo "$(date -u +%FT%TZ) MISS: Last run was $last_run (expected today). Triggering scan..."

result=$(curl -sf -X POST "$SCRAPE_URL/api/job-sources/scan" 2>/dev/null) || {
  echo "$(date -u +%FT%TZ) ERROR: Scan trigger failed"
  exit 1
}

status=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['scan']['status'])" 2>/dev/null)
echo "$(date -u +%FT%TZ) Scan triggered: status=$status"

# Wait for scan to complete
echo "$(date -u +%FT%TZ) Waiting for scan to complete (poll every ${POLL_INTERVAL}s, timeout ${POLL_TIMEOUT}s)..."
elapsed=0
while [ "$elapsed" -lt "$POLL_TIMEOUT" ]; do
  sleep "$POLL_INTERVAL"
  elapsed=$((elapsed + POLL_INTERVAL))

  stage=$(curl -sf "$SCRAPE_URL/api/scrape-schedule" 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['current_stage'])" 2>/dev/null) || stage="unknown"

  if [ "$stage" != "searching" ]; then
    echo "$(date -u +%FT%TZ) Scan finished: stage=$stage"
    break
  fi

  echo "$(date -u +%FT%TZ) Still searching... (${elapsed}s elapsed)"
done

if [ "$stage" = "searching" ]; then
  echo "$(date -u +%FT%TZ) WARN: Scan still searching after ${POLL_TIMEOUT}s. Continuing anyway."
fi

# Run work-mode resolution if CLI is available
if command -v "$RESUME_CLI" &>/dev/null; then
  ws_args=()
  if [ -n "$WORKSPACE" ]; then
    ws_args=(--workspace "$WORKSPACE")
  fi
  echo "$(date -u +%FT%TZ) Running resolve-sources to classify work modes..."
  "$RESUME_CLI" jobs resolve-sources --apply "${ws_args[@]}" 2>&1 && \
    echo "$(date -u +%FT%TZ) resolve-sources complete." || \
    echo "$(date -u +%FT%TZ) WARN: resolve-sources failed (non-fatal)."
else
  echo "$(date -u +%FT%TZ) SKIP: '$RESUME_CLI' not found. Run 'resume-builder jobs resolve-sources --apply' manually."
fi
