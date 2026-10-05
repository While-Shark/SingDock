#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ "${1:-serve}" != serve ]]; then exec singdock "$@"; fi
[[ "${ENABLE_WARP:-false}" =~ ^(true|false)$ ]] || { echo "ENABLE_WARP must be true or false"; exit 1; }
mkdir -p /opt/sing-box /run/singdock /var/lib/cloudflare-warp
supervisor_pid=''
cleanup() {
  if [[ -n "$supervisor_pid" ]]; then
    kill -TERM "$supervisor_pid" 2>/dev/null || true
    wait "$supervisor_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
# Start supervisor without sing-box while generating/checking the config.
sed 's/autostart=true/autostart=false/' /opt/singdock/docker/supervisord.conf > /run/singdock/bootstrap.conf
supervisord -c /run/singdock/bootstrap.conf &
supervisor_pid=$!
for _ in {1..30}; do
  [[ -S /run/singdock/supervisor.sock ]] && break
  kill -0 "$supervisor_pid" || exit 1
  sleep 1
done
ctl() { supervisorctl -c /opt/singdock/docker/supervisord.conf "$@"; }
if [[ "${ENABLE_WARP:-false}" == true ]]; then
  command -v warp-cli >/dev/null || { echo "Rebuild with INSTALL_WARP=true"; exit 1; }
  [[ "${WARP_ACCEPT_TOS:-false}" == true ]] || { echo "Set WARP_ACCEPT_TOS=true after accepting Cloudflare terms"; exit 1; }
  ctl start warp-svc
  ready=false
  for _ in {1..30}; do
    if timeout 5 warp-cli --accept-tos status >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true ]] || { echo "warp-svc not ready"; exit 1; }
  timeout 30 warp-cli --accept-tos registration show >/dev/null 2>&1 ||
    timeout 60 warp-cli --accept-tos registration new
  timeout 30 warp-cli --accept-tos mode proxy
  timeout 30 warp-cli --accept-tos proxy port 40000
  timeout 30 warp-cli --accept-tos connect
  ready=false
  for _ in {1..15}; do
    if curl --connect-timeout 3 --max-time 5 -fsSL --proxy socks5h://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace | grep -q '^warp=on'; then ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true ]] || { echo "WARP egress check failed; no direct fallback"; exit 1; }
fi
singdock init
ctl start sing-box
# Startup failure must fail the container instead of looking healthy.
ctl status sing-box | grep -q RUNNING
echo "SingDock ready. Run: docker exec -it singdock singdock menu"
wait "$supervisor_pid"
