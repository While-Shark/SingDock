#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export SINGDOCK_SOURCE_ONLY=1 SBP_SKIP_DEPS=1
export SBP_ROOT="${SBP_ROOT:-/opt/sing-box/.bootstrap}"
requested_warp="${ENABLE_WARP:-false}"
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ "${1:-menu}" == gui-info ]]; then
  exec python3 /opt/singdock/web/gui_info.py
fi
# Keep bootstrap executables away from the writable data volume.
export SBP_BIN_DIR=/opt/singdock/bootstrap-bin
source /opt/singdock/upstream/sing-box-plus.sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
safe_source_env() {
  local file="$1" parsed key value
  [[ -e "$file" ]] || return 1
  parsed=$(mktemp /run/singdock/env.XXXXXX)
  if ! python3 /opt/singdock/docker/read_env.py "$file" > "$parsed"; then
    rm -f "$parsed"
    die "持久化配置格式不安全，已拒绝加载"
  fi
  while IFS= read -r -d '' key && IFS= read -r -d '' value; do
    printf -v "$key" '%s' "$value"
  done < "$parsed"
  rm -f "$parsed"
}
SCRIPT_NAME="SingDock · Sing-Box-Plus 容器版"
ctl() { supervisorctl -c /opt/singdock/docker/supervisord.conf "$@"; }

# Keep upstream configuration/link functions; override only host operations.
load_env() {
  safe_source_env "$SB_DIR/env.conf" || true
  ENABLE_WARP="$requested_warp"
  BIN_PATH=/usr/local/bin/sing-box
}
install_deps() { :; }
sbp_bootstrap() { :; }
install_singbox() { "$BIN_PATH" version; }
write_systemd() { :; }
open_firewall() { echo "请在 VPS 安全组/宿主防火墙放行节点端口（singdock ports）。"; }
enable_bbr() { echo "BBR 属于宿主内核设置，请在 VPS 上配置。"; }
uninstall_all() { echo "请在宿主执行 docker compose down；备份后再手动删除 data。"; }
sb_service_state() { ctl status sing-box 2>/dev/null || true; }
restart_service() { "$BIN_PATH" check -c "$CONF_JSON"; ctl restart sing-box; }
ensure_warpcli_proxy() {
  [[ "$ENABLE_WARP" == true ]] || return 0
  command -v warp-cli >/dev/null || die "请设置 INSTALL_WARP=true 并重新构建镜像"
  timeout 10 warp-cli --accept-tos status >/dev/null
}
get_ip4() {
  if [[ -n "${PUBLIC_HOST:-}" ]]; then printf '%s\n' "$PUBLIC_HOST"; return; fi
  curl -4 -fsSL --connect-timeout 5 --max-time 10 https://ipv4.icanhazip.com ||
    die "公网地址检测失败，请设置 PUBLIC_HOST"
}
get_ip6() {
  if [[ -n "${PUBLIC_HOST:-}" ]]; then printf '%s\n' "$PUBLIC_HOST"; return; fi
  curl -6 -fsSL --connect-timeout 5 --max-time 10 https://ipv6.icanhazip.com || true
}
# Upstream command substitution loses PORTS array updates; allocate in this shell.
save_all_ports() {
  local var port
  PORTS=()
  for var in $(compgen -A variable PORT_ | sort); do
    port="${!var}"
    if [[ -n "$port" ]]; then
      [[ "$port" =~ ^[0-9]+$ && "$port" -ge 1024 && "$port" -le 65535 ]] || die "无效端口: $var"
      [[ " ${PORTS[*]} " != *" $port "* ]] || die "端口重复: $port"
      PORTS+=("$port")
    fi
  done
  for var in $(compgen -A variable PORT_ | sort); do
    if [[ -z "${!var}" ]]; then
      while :; do
        port=$((10000 + RANDOM % 50000))
        [[ "$port" != "$WARP_SOCKS_PORT" && "$port" != "${GUI_PORT:-18100}" && " ${PORTS[*]} " != *" $port "* ]] || continue
        ss -H -lntu | awk '{print $5}' | grep -Eq ":$port$" && continue
        printf -v "$var" '%s' "$port"
        PORTS+=("$port")
        break
      done
    fi
  done
  save_ports
}
# Rename the fixed upstream function, then validate an atomic candidate.
eval "$(declare -f write_config | sed '1s/write_config/upstream_write_config/')"
write_config() {
  local target="$CONF_JSON" candidate
  candidate=$(mktemp "$SB_DIR/config.XXXXXX")
  CONF_JSON="$candidate"
  upstream_write_config
  # 1.13 removed the legacy block outbound; it is unused by this script.
  # Disabled WARP must remove its listeners too (upstream kept them direct).
  jq --arg enabled "$ENABLE_WARP" '
    .outbounds |= map(select(.type != "block")) |
    .route.default_domain_resolver = "dns-remote" |
    if $enabled != "true" then
      .inbounds |= map(select(.tag | endswith("-warp") | not))
    else . end' "$candidate" > "$candidate.clean"
  mv "$candidate.clean" "$candidate"
  if ! "$BIN_PATH" check -c "$candidate"; then
    rm -f "$candidate"; CONF_JSON="$target"; return 1
  fi
  mv "$candidate" "$target"
  CONF_JSON="$target"
}
initialize() {
  ensure_dirs
  # Serialize menu/init/port changes to protect persisted credentials.
  exec 9>"$SB_DIR/.manage.lock"
  flock -x 9
  write_config
  flock -u 9
}
deploy_native() { initialize; restart_service; print_links; }
rotate_ports() {
  ensure_installed_or_hint || return 1
  local var
  exec 9>"$SB_DIR/.manage.lock"; flock -x 9
  cp "$SB_DIR/ports.env" "$SB_DIR/ports.env.bak"
  for var in $(compgen -A variable PORT_); do printf -v "$var" ''; done
  # Prevent upstream load_ports from restoring the old values.
  mv "$SB_DIR/ports.env" "$SB_DIR/ports.env.previous"
  if ! ( write_config ); then
    mv "$SB_DIR/ports.env.previous" "$SB_DIR/ports.env"
    flock -u 9; return 1
  fi
  rm -f "$SB_DIR/ports.env.previous"
  flock -u 9
  restart_service
  open_firewall
}
print_links() {
  if [[ "$requested_warp" == true ]]; then print_links_grouped "${1:-4}"
  else
    print_links_grouped "${1:-4}" | awk '/【WARP 节点/ {skip=1} /📌/ {skip=0} !skip && !/-warp/'
  fi
}
banner() {
  echo "SingDock（原脚本容器适配）"
  echo "1) 初始化/重新应用配置  2) IPv4 链接  6) IPv6 链接"
  echo "3) 重启  4) 更换端口  5) BBR 说明  8) 卸载说明  0) 退出"
  sb_service_state
}
menu() {
  local op
  while :; do
    banner
    read -rp "选择: " op || return 0
    case "$op" in
      1) initialize; restart_service; print_links ;;
      2) print_links 4 ;; 6) print_links 6 ;;
      3) restart_service ;; 4) rotate_ports ;;
      5) enable_bbr ;; 8) uninstall_all ;; 0) return ;;
    esac
  done
}
case "${1:-menu}" in
  init) initialize ;;
  menu) menu ;;
  links) print_links "${2:-4}" ;;
  restart) restart_service ;;
  rotate-ports) rotate_ports ;;
  status) ctl status ;;
  ports) jq -r '.inbounds[] | [.tag, (.listen_port|tostring), (if .type=="hysteria2" or .type=="tuic" then "UDP" elif .type=="shadowsocks" then "TCP+UDP" else "TCP" end)] | @tsv' "$CONF_JSON" ;;
  check) "$BIN_PATH" check -c "$CONF_JSON" ;;
  *) echo "用法: singdock [menu|init|links [4|6]|restart|rotate-ports|status|ports|check|gui-info]" >&2; exit 2 ;;
esac
