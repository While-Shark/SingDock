#!/usr/bin/env bash
set -euo pipefail
ctl() { supervisorctl -c /opt/singdock/docker/supervisord.conf status "$1" | grep -q RUNNING; }
ctl sing-box
if [[ "${ENABLE_WARP:-false}" == true ]]; then
  ctl warp-svc
  curl -fsSL --connect-timeout 2 --max-time 3 --proxy socks5h://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace | grep -q '^warp=on'
fi
if [[ "${ENABLE_GUI:-false}" == true ]]; then
  ctl gui
fi
