#!/usr/bin/env bash
# Dev: start the stack + TWO Cloudflare quick tunnels (no account/token needed) — the dashboard and the
# API are separate origins — then write the URLs into .env and recreate api, worker and web (no rebuild):
#   APP_BASE_URL=<web tunnel>   API_BASE_URL=API_PUBLIC_URL=<api tunnel>   COOKIE_SAMESITE=none
# (two *.trycloudflare.com hosts are cross-site, so the session cookie must be SameSite=None; Secure).
# Uses the host's `cloudflared` if installed (background processes; logs/pids in .cloudflared-{web,api}.*),
# else the `tunnel`/`tunnel-web` compose containers. URLs stay the same until the tunnels are restarted.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose"

if grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=.+' .env 2>/dev/null; then
  $COMPOSE --profile tunnel-named up -d --build
  echo "Named tunnel running; dashboard: $(grep -E '^APP_BASE_URL=' .env | cut -d= -f2-)  API: $(grep -E '^API_BASE_URL=' .env | cut -d= -f2-)"
  exit 0
fi

find_url() { grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$@" 2>/dev/null | tail -1 || true; }
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
env_set() {  # replace KEY=... in .env, or append it
  if grep -qE "^$1=" .env; then sed -i -E "s#^$1=.*#$1=$2#" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}

# Images are built by `make up` / `docker compose up -d --build`; here only start what is not running.
$COMPOSE up -d

web_port=$(env_get WEB_PORT); web_port=${web_port:-3000}
api_port=$(env_get API_PORT); api_port=${api_port:-8000}

if command -v cloudflared >/dev/null 2>&1; then
  start_host_tunnel() {  # name port
    local log=".cloudflared-$1.log" pid=".cloudflared-$1.pid"
    if [ -f "$pid" ] && kill -0 "$(cat "$pid")" 2>/dev/null; then
      echo "reusing running cloudflared for $1 (pid $(cat "$pid"))"
    else
      : > "$log"
      nohup cloudflared tunnel --no-autoupdate --url "http://localhost:$2" > "$log" 2>&1 &
      echo $! > "$pid"
    fi
  }
  # Older single-tunnel layout (web only): stop it.
  if [ -f .cloudflared.pid ]; then kill "$(cat .cloudflared.pid)" 2>/dev/null || true; rm -f .cloudflared.pid .cloudflared.log; fi
  start_host_tunnel web "$web_port"
  start_host_tunnel api "$api_port"
  get_web() { find_url .cloudflared-web.log; }
  get_api() { find_url .cloudflared-api.log; }
else
  $COMPOSE --profile tunnel up -d tunnel tunnel-web
  get_web() { $COMPOSE --profile tunnel logs tunnel-web 2>&1 | find_url; }
  get_api() { $COMPOSE --profile tunnel logs tunnel 2>&1 | find_url; }
fi

web=""; api=""
for _ in $(seq 1 45); do
  web=$(get_web); api=$(get_api)
  [ -n "$web" ] && [ -n "$api" ] && break
  sleep 2
done
if [ -z "$web" ] || [ -z "$api" ]; then
  echo "tunnel URL(s) not found (web='$web' api='$api'); see .cloudflared-{web,api}.log or '$COMPOSE --profile tunnel logs'" >&2
  exit 1
fi

if [ "$(env_get APP_BASE_URL)" != "$web" ] || [ "$(env_get API_BASE_URL)" != "$api" ] \
  || [ "$(env_get API_PUBLIC_URL)" != "$api" ] || [ "$(env_get COOKIE_SAMESITE)" != "none" ]; then
  env_set APP_BASE_URL "$web"
  env_set API_BASE_URL "$api"
  env_set API_PUBLIC_URL "$api"
  env_set COOKIE_SAMESITE none
  $COMPOSE up -d --no-deps --no-build --force-recreate api worker web
fi

cat <<MSG

HootPR dashboard: $web
HootPR API:       $api
Set these on the providers (they change whenever the tunnels are restarted) — all on the API URL:
  GitHub App  webhook URL:         $api/api/webhooks/github
              callback URL:        $api/api/auth/github/callback
              setup URL:           $api/api/github/setup
              homepage URL:        $web
  GitLab OAuth app redirect URI:   $api/api/auth/gitlab/callback   (project hooks re-register via Sync)
  Razorpay webhook:                $api/api/webhooks/razorpay
Stop the tunnels: make tunnel-stop
MSG
