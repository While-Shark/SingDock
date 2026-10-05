#!/usr/bin/env bash
# Run after docker build -t singdock:test .
set -Eeuo pipefail
image="${1:-singdock:test}"
suffix="$$"
net="singdock-test-$suffix"
server="singdock-server-$suffix"
http="singdock-http-$suffix"
volume="singdock-data-$suffix"
cleanup() {
  docker rm -f "$server" "$http" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$net" >/dev/null
docker volume create "$volume" >/dev/null
docker run -d --name "$http" --network "$net" busybox:1.37 sh -c \
  'mkdir -p /www; echo singdock-smoke-ok > /www/index.html; exec httpd -f -p 8080 -h /www' >/dev/null
start() {
  docker run -d --name "$server" --network "$net" \
    -e PUBLIC_HOST=example.com -e ENABLE_WARP=false \
    -v "$volume:/opt/sing-box" "$image" >/dev/null
  for _ in {1..60}; do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$server")" == healthy ]]; then return; fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$server")" != true ]]; then break; fi
    sleep 1
  done
  docker logs "$server"; return 1
}
start
docker exec "$server" singdock check
docker exec "$server" jq -e '.inbounds | length == 10' /opt/sing-box/config.json >/dev/null
docker exec "$server" jq -e '.route.default_domain_resolver as $resolver |
  $resolver == "dns-remote" and any(.dns.servers[]; .tag == $resolver)' /opt/sing-box/config.json >/dev/null
docker exec "$server" sh -c 'test "$(cut -d= -f2 /opt/sing-box/ports.env | sort -u | wc -l)" -eq 20'
identity=$(docker exec "$server" sh -c 'sha256sum /opt/sing-box/creds.env /opt/sing-box/cert/key.pem /opt/sing-box/ports.env')
docker exec "$server" singdock init
test "$identity" = "$(docker exec "$server" sh -c 'sha256sum /opt/sing-box/creds.env /opt/sing-box/cert/key.pem /opt/sing-box/ports.env')"
docker stop -t 10 "$server" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$server")" != 137
docker rm "$server" >/dev/null
start
test "$identity" = "$(docker exec "$server" sh -c 'sha256sum /opt/sing-box/creds.env /opt/sing-box/cert/key.pem /opt/sing-box/ports.env')"
docker exec "$server" singdock links > /tmp/singdock-links-"$suffix"
test "$(grep -Ec '^  (vless|trojan|hy2|vmess|ss|tuic|anytls)://' /tmp/singdock-links-"$suffix")" -ge 10
! grep -q -- '-warp' /tmp/singdock-links-"$suffix"
rm /tmp/singdock-links-"$suffix"
# Actual Shadowsocks TCP handshake -> isolated HTTP server, no public probe.
docker exec "$server" bash -c '
  jq --arg server "127.0.0.1" ".inbounds[] | select(.tag == \"ss\") |
    {inbounds:[{type:\"mixed\",listen:\"127.0.0.1\",listen_port:19080}],
     outbounds:[{type:\"shadowsocks\",tag:\"proxy\",server:\$server,
       server_port:.listen_port,method:.method,password:.password}],
     dns:{servers:[{type:\"local\",tag:\"dns-local\"}]},
     route:{final:\"proxy\",default_domain_resolver:\"dns-local\"}}" /opt/sing-box/config.json > /tmp/client.json
  sing-box check -c /tmp/client.json'
docker exec -d "$server" sing-box run -c /tmp/client.json
http_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$http")
docker exec "$server" curl --retry 10 --retry-connrefused --retry-delay 1 \
  --max-time 20 --noproxy '' --proxy socks5h://127.0.0.1:19080 "http://$http_ip:8080/" | grep -q singdock-smoke-ok
docker exec "$server" singdock rotate-ports
docker exec "$server" singdock check
docker exec "$server" sh -c 'test "$(cut -d= -f2 /opt/sing-box/ports.env | sort -u | wc -l)" -eq 20'
echo "PASS: config, identity persistence, shutdown, links, Shadowsocks TCP, port rotation"
