#!/bin/bash
set -u

# Persistent macOS watchdog for the fuxi Build workflow. It uses the user's
# existing `gh` authentication and never starts, cancels, or reruns a build.
# It only observes runs and preserves terminal diagnostics locally.
REPO="kkkpc/unixnu-fuxi-oddlylabs"
BRANCH="native-ufs-root"
WORKSPACE="/Users/benm1/Documents/Codex/unixnu-fuxi-gpt-codex/unixnu-fuxi-oddlylabs"
LOG_DIR="/Users/benm1/Library/Logs/unixnu-fuxi-actions-watchdog"
STATE_FILE="$LOG_DIR/state.json"
CODEX_ALERT_FILE="$LOG_DIR/codex-alert.json"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PATH

mkdir -p "$LOG_DIR"

stamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log() { printf '[%s] %s\n' "$(stamp)" "$*" >> "$LOG_DIR/watchdog.log"; }

run_view() {
  gh run view "$1" --repo "$REPO" \
    --json status,conclusion,headSha,url,createdAt,updatedAt,jobs
}

record_terminal_diagnostics() {
  local run_id="$1"
  local run_log="$LOG_DIR/run-${run_id}-failed.log"
  local summary="$LOG_DIR/run-${run_id}-summary.json"
  if [ -f "$run_log" ]; then
    return
  fi
  gh run view "$run_id" --repo "$REPO" --json status,conclusion,headSha,url,createdAt,updatedAt,jobs > "$summary" 2>&1 || true
  gh run view "$run_id" --repo "$REPO" --log-failed > "$run_log" 2>&1 || true
  local first_error
  first_error=$(rg -m 1 -i 'error:|error |failed|failure|not found|undefined|unresolved|no reference|traceback' "$run_log" 2>/dev/null || true)
  log "terminal run=${run_id}; diagnostics=${run_log}"
  if [ -n "$first_error" ]; then
    log "first diagnostic: ${first_error}"
    jq -n \
      --arg repository "$REPO" \
      --arg branch "$BRANCH" \
      --arg run_id "$run_id" \
      --arg url "$(jq -r '.url // empty' "$summary" 2>/dev/null || true)" \
      --arg head_sha "$(jq -r '.headSha // empty' "$summary" 2>/dev/null || true)" \
      --arg diagnostic "$first_error" \
      --arg detected_at "$(stamp)" \
      '{repository:$repository,branch:$branch,run_id:($run_id|tonumber),url:$url,head_sha:$head_sha,diagnostic:$diagnostic,detected_at:$detected_at,handled:false}' \
      > "$CODEX_ALERT_FILE"
    osascript -e 'display notification "GitHub Build failed; Codex alert file updated" with title "UniXNU watchdog"' \
      >/dev/null 2>&1 || true
  fi
}

while true; do
  current=$(gh run list --repo "$REPO" --workflow Build --branch "$BRANCH" --limit 1 \
    --json databaseId,status,conclusion,headSha,url,createdAt,updatedAt 2>&1 || true)
  if ! printf '%s' "$current" | jq -e 'length > 0' >/dev/null 2>&1; then
    log "poll failed or no Build run: ${current}"
    sleep 60
    continue
  fi

  run_id=$(printf '%s' "$current" | jq -r '.[0].databaseId')
  signature=$(printf '%s' "$current" | jq -c '.[0]')
  previous=$(cat "$STATE_FILE" 2>/dev/null || true)
  if [ "$signature" != "$previous" ]; then
    printf '%s\n' "$signature" > "$STATE_FILE"
    log "state change: ${signature}"
  fi

  status=$(printf '%s' "$current" | jq -r '.[0].status')
  if [ "$status" = "completed" ]; then
    conclusion=$(printf '%s' "$current" | jq -r '.[0].conclusion')
    record_terminal_diagnostics "$run_id"
    log "terminal state observed: run=${run_id} conclusion=${conclusion}"
  else
    log "run=${run_id} status=${status}"
  fi
  sleep 60
done
