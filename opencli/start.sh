#!/bin/sh
set -eu

DAEMON_PORT="${OPENCLI_DAEMON_PORT:-19827}"
API_PORT="${OPENCLI_API_PORT:-19826}"

export OPENCLI_DAEMON_PORT="$DAEMON_PORT"

DAEMON_JS="$(npm root -g)/@jackwener/opencli/dist/src/daemon.js"

node "$DAEMON_JS" &
daemon_pid=$!

# The OpenCLI daemon binds to 127.0.0.1 only. Forward container port 19825 to it so
# the *host* Chrome extension can connect to localhost:19825.
socat TCP-LISTEN:19825,fork,reuseaddr TCP:127.0.0.1:"$DAEMON_PORT" &
socat_pid=$!

cleanup() {
  kill "$socat_pid" "$daemon_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

# Wait briefly for daemon boot.
for i in $(seq 1 60); do
  if opencli daemon status >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

exec python3 -u /srv/server.py --host 0.0.0.0 --port "$API_PORT"
