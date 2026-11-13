#!/usr/bin/env sh
# Claude Code hook shim: find Python 3.9+ and hand the payload to cli_hook.py.
#   run-hook.sh pre|post
# Fails CLOSED: with no usable Python, or if cli_hook.py crashes, a pre-tool
# payload that mentions openshell (any case) gets an "ask" instead of running.

dir=$(cd "$(dirname "$0")" && pwd)
payload=$(cat)

ask() {
  if [ "$1" = pre ] && printf '%s' "$payload" | tr -d "\"'\\\\" | grep -qi openshell; then
    printf '%s\n' "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"ask\",\"permissionDecisionReason\":\"$2\"}}"
  fi
  exit 0
}

for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    if printf '%s' "$payload" | "$py" "$dir/cli_hook.py" --cli claude --event "$1"; then
      exit 0
    fi
    ask "$1" "The OpenShell guard crashed and this command mentions openshell. Review it manually before allowing."
  fi
done

ask "$1" "The OpenShell guard could not run (Python 3.9+ is unavailable) and this command mentions openshell. Review it manually before allowing."
