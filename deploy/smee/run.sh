#!/bin/sh
# Dev-only webhook relay (spec §3.1): smee.io channels -> api container.
set -eu
npm install --global --silent --no-fund --no-audit smee-client >/dev/null
pids=""
relay() {
  if [ -n "$1" ]; then
    echo "smee: $1 -> $2"
    smee --url "$1" --target "$2" &
    pids="$pids $!"
  fi
}
relay "${SMEE_URL:-}" "http://api:8000/api/webhooks/github"
relay "${SMEE_GITLAB_URL:-}" "http://api:8000/api/webhooks/gitlab"
relay "${SMEE_RAZORPAY_URL:-}" "http://api:8000/api/webhooks/razorpay"
if [ -z "$pids" ]; then
  echo "smee: no SMEE_URL / SMEE_GITLAB_URL / SMEE_RAZORPAY_URL set; nothing to relay"
  exec sleep infinity
fi
# exit (and let compose restart us) as soon as any relay dies
while :; do
  for p in $pids; do
    if ! kill -0 "$p" 2>/dev/null; then echo "smee: relay $p exited"; exit 1; fi
  done
  sleep 5
done
