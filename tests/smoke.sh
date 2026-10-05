#!/usr/bin/env bash
# Run after docker build -t singdock:test .; optional second argument: bridge|host.
set -Eeuo pipefail
image="${1:-singdock:test}"
mode="${2:-bridge}"
[[ "$mode" == bridge || "$mode" == host ]] || { echo "Network mode must be bridge or host" >&2; exit 2; }
suffix="$$"
net="singdock-test-$suffix"
server="singdock-server-$suffix"
http="singdock-http-$suffix"
volume="singdock-data-$suffix"
cleanup() {
  docker rm -f "$server" "$http" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -f /tmp/singdock-links-"$suffix"
}
trap cleanup EXIT
trap 'echo "Smoke test failed at line $LINENO ($mode)" >&2; docker logs --tail 80 "$server" >&2 || true' ERR
docker network create "$net" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$http" --network "$net" busybox:1.37 sh -c \
  'mkdir -p /www; echo singdock-smoke-ok > /www/index.html; exec httpd -f -p 8080 -h /www' >/dev/null
start() {
  local server_network="$net"
  [[ "$mode" != host ]] || server_network=host
  docker run -d --name "$server" --network "$server_network" \
    --security-opt no-new-privileges:true --cap-drop NET_RAW --cap-drop MKNOD --cap-drop SYS_CHROOT \
    -e PUBLIC_HOST=example.com -e ENABLE_WARP=false \
    -e ENABLE_GUI=true -e GUI_USERNAME=smoke-manager -e GUI_PATH=auto \
    -e GUI_PASSWORD= -e GUI_PORT=18100 \
    -e REALITY_SERVER=localhost -e REALITY_SERVERS=localhost \
    -v "$volume:/opt/sing-box" "$image" >/dev/null
  for _ in {1..60}; do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$server")" == healthy ]]; then return; fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$server")" != true ]]; then break; fi
    sleep 1
  done
  docker logs "$server"; return 1
}
start
gui_path=$(docker exec "$server" cat /opt/sing-box/gui-path)
[[ "$gui_path" =~ ^/panel-[0-9a-f]{32}$ ]]
gui_password_hash=$(docker exec "$server" sha256sum /opt/sing-box/gui-password)
docker exec "$server" sh -c 'test "$(stat -c %a /opt/sing-box/gui-password)" = 600'
# Verify local login discovery without putting the generated secret in CI logs.
docker exec "$server" singdock gui-info | grep -q '^密码: '
if docker logs "$server" 2>&1 | docker exec -i "$server" python3 -c 'import pathlib,sys; p=pathlib.Path("/opt/sing-box/gui-password").read_text().strip(); sys.exit(0 if p in sys.stdin.read() else 1)'; then
  echo "Generated GUI password leaked into startup logs" >&2; exit 1
fi
docker logs "$server" 2>&1 | grep -F "SingDock GUI: http://127.0.0.1:18100$gui_path/"
docker exec "$server" sh -c 'test "$(stat -c %a /opt/sing-box/gui-path)" = 600'
docker exec "$server" singdock check
docker exec "$server" jq -e '.inbounds | length == 10' /opt/sing-box/config.json >/dev/null
docker exec "$server" jq -e '.route.default_domain_resolver as $resolver |
  $resolver == "dns-remote" and any(.dns.servers[]; .tag == $resolver)' /opt/sing-box/config.json >/dev/null
docker exec "$server" sh -c 'test "$(cut -d= -f2 /opt/sing-box/ports.env | sort -u | wc -l)" -eq 20'
identity=$(docker exec "$server" sh -c 'sha256sum /opt/sing-box/creds.env /opt/sing-box/cert/key.pem /opt/sing-box/ports.env')
docker exec "$server" singdock init
test "$identity" = "$(docker exec "$server" sh -c 'sha256sum /opt/sing-box/creds.env /opt/sing-box/cert/key.pem /opt/sing-box/ports.env')"
# A rejected candidate must not replace the valid configuration.
config_before=$(docker exec "$server" sha256sum /opt/sing-box/config.json)
docker exec "$server" sh -c 'cp /opt/sing-box/env.conf /tmp/env.conf.before-test;
  sed -i "s/^REALITY_SERVER_PORT=.*/REALITY_SERVER_PORT=65536/" /opt/sing-box/env.conf'
if docker exec "$server" singdock init; then
  echo "Invalid port unexpectedly passed configuration validation" >&2
  exit 1
fi
test "$config_before" = "$(docker exec "$server" sha256sum /opt/sing-box/config.json)"
docker exec "$server" sh -c 'mv /tmp/env.conf.before-test /opt/sing-box/env.conf'
docker exec "$server" singdock check
docker stop -t 10 "$server" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$server")" != 137
docker rm "$server" >/dev/null
start
test "$gui_path" = "$(docker exec "$server" cat /opt/sing-box/gui-path)"
test "$gui_password_hash" = "$(docker exec "$server" sha256sum /opt/sing-box/gui-password)"
docker logs "$server" 2>&1 | grep -F "SingDock GUI: http://127.0.0.1:18100$gui_path/"
test "$identity" = "$(docker exec "$server" sh -c 'sha256sum /opt/sing-box/creds.env /opt/sing-box/cert/key.pem /opt/sing-box/ports.env')"
docker exec "$server" singdock links > /tmp/singdock-links-"$suffix"
test "$(grep -Ec '^  (vless|trojan|hy2|vmess|ss|tuic|anytls)://' /tmp/singdock-links-"$suffix")" -ge 10
! grep -q -- '-warp' /tmp/singdock-links-"$suffix"
rm /tmp/singdock-links-"$suffix"
# Local TLS 1.3 / H2 target for authenticated Reality handshakes.
# Only the test fixture binds loopback 443; deployment ports remain random.
docker exec -d "$server" sh -c 'exec openssl s_server -accept 127.0.0.1:443 \
  -cert /opt/sing-box/cert/fullchain.pem -key /opt/sing-box/cert/key.pem \
  -tls1_3 -alpn h2 -www > /tmp/reality-target.log 2>&1'
target_ready=false
for _ in {1..10}; do
  if docker exec "$server" timeout 5 openssl s_client -connect 127.0.0.1:443 \
      -servername localhost -tls1_3 -alpn h2 -verify_return_error \
      -CAfile /opt/sing-box/cert/fullchain.pem </dev/null >/dev/null 2>&1; then
    target_ready=true; break
  fi
  sleep 1
done
if [[ "$target_ready" != true ]]; then
  docker exec "$server" cat /tmp/reality-target.log >&2 || true
  exit 1
fi
# Keep SNI localhost, dial its local fixture directly rather than public DNS.
docker exec "$server" sh -c '
  jq "(.inbounds[] | select(.tls.reality.enabled == true) | .tls.reality.handshake.server) = \"127.0.0.1\"" \
    /opt/sing-box/config.json > /tmp/reality-config.json
  chmod 600 /tmp/reality-config.json
  mv /tmp/reality-config.json /opt/sing-box/config.json'
docker exec "$server" singdock restart
# Actual protocol handshakes -> isolated HTTP server, no public probe.
# Hysteria2 and TUIC use UDP to the node; the target request remains TCP.
docker cp "$(dirname "$0")/client_config.py" "$server:/tmp/client_config.py"
http_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$http")
for protocol in ss ss2022 vmess-ws hy2 hy2-obfs tuic-v5 anytls vless-reality vless-grpcr trojan-reality; do
  client="/tmp/client-$protocol.json"
  port=$(docker exec "$server" python3 /tmp/client_config.py /opt/sing-box/config.json "$protocol" "$client")
  docker exec "$server" sing-box check -c "$client"
  docker exec -d "$server" sh -c 'exec sing-box run -c "$1" > "$2" 2>&1' sh "$client" "/tmp/client-$protocol.log"
  if ! docker exec "$server" curl --retry 10 --retry-connrefused --retry-delay 1 \
      --max-time 20 --noproxy '' --proxy "socks5h://127.0.0.1:$port" "http://$http_ip:8080/" | grep -q singdock-smoke-ok; then
    echo "Proxy handshake failed: $protocol" >&2
    docker exec "$server" cat "/tmp/client-$protocol.log" >&2 || true
    exit 1
  fi
  echo "PASS: $protocol handshake and TCP target"
done
docker cp "$(dirname "$0")/gui_smoke.py" "$server:/tmp/gui_smoke.py"
docker exec "$server" python3 /tmp/gui_smoke.py
docker exec "$server" singdock rotate-ports
docker exec "$server" singdock check
docker exec "$server" sh -c 'test "$(cut -d= -f2 /opt/sing-box/ports.env | sort -u | wc -l)" -eq 20'
echo "PASS ($mode): config, rejected candidate, identity persistence, shutdown, links, ten protocol handshakes, port rotation"
