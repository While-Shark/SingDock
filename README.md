# SingDock

把 [Sing-Box-Plus](https://github.com/Alvin9999-newpac/Sing-Box-Plus) 放进 Debian 容器，方便在 CentOS 7 等宿主机部署。保留原脚本的配置、证书、节点链接和中文菜单，只适配容器运行所需的部分。

**当前为首版测试实现。** 普通镜像与可选 WARP 镜像已通过 AMD64、ARM64 构建；普通容器已通过启动、配置校验、身份持久化、端口更换及真实 Shadowsocks TCP 握手测试。目标是解决用户空间依赖，不保证旧宿主内核能运行所有协议或官方 WARP；其余协议握手和 CentOS 7/WARP 需实测后确认。

AMD64、ARM64 的 bridge/host 两种网络、错误配置保护，以及 Shadowsocks、Shadowsocks 2022、VMess WS、Hysteria2（含混淆）、TUIC、AnyTLS 七种节点的真实链路均已通过。WARP 镜像构建和二进制运行检查也已通过，但不代表注册、连接或出口验证通过。CI 现已加入三种 Reality 节点的本地 TLS 握手测试，新增结果以 [Actions](https://github.com/While-Shark/SingDock/actions) 为准。

## Docker Compose

需要已安装 Docker；支持 Compose V2，也可以用支持 Compose Specification 的独立 `docker-compose`。

```bash
git clone https://github.com/While-Shark/SingDock.git
cd SingDock
cp .env.example .env
# 编辑 .env，填写 PUBLIC_HOST=你的公网IP或域名
docker compose up -d --build
docker compose logs --tail=100
docker compose exec singdock singdock links
docker compose exec singdock singdock ports
```

首次启动生成 10 个直连节点；端口、证书、密钥保存在 `data/sing-box`。再次启动或重建镜像会保留节点身份。不在启动日志输出凭据；手动查看链接时请妥善保管。

使用 Linux **host 网络**，不需要逐个映射随机端口。请按 `ports` 输出在 VPS 的云安全组和宿主防火墙开放 TCP/UDP。容器不修改宿主防火墙、BBR、systemd 或宿主文件。443 不会默认占用；生成端口在 10000–59999 之间，并检查当前监听冲突。

CentOS 的 SELinux 挂载使用 `:Z`。数据目录属于单个容器，不要与多个副本共享。

## Docker run

```bash
docker build -t singdock:local .
mkdir -p data/sing-box data/warp
docker run -d --name singdock --restart unless-stopped --network host \
  -e PUBLIC_HOST=你的公网IP或域名 \
  -v "$PWD/data/sing-box:/opt/sing-box:Z" \
  -v "$PWD/data/warp:/var/lib/cloudflare-warp:Z" \
  --log-opt max-size=10m --log-opt max-file=3 singdock:local
docker exec -it singdock singdock menu
```

## 原菜单与常用命令

```bash
docker compose exec singdock singdock menu
docker compose exec singdock singdock links       # IPv4/域名链接
docker compose exec singdock singdock links 6     # IPv6 链接
docker compose exec singdock singdock ports
docker compose exec singdock singdock status
docker compose exec singdock singdock check
docker compose exec singdock singdock restart
docker compose exec singdock singdock rotate-ports
```

更换端口后，客户端链接和防火墙规则也要更新。原菜单的安装操作变为生成/验证配置；BBR 提示到宿主设置；卸载提示用 Compose 停止，不自动删除持久化目录。

协议沿用上游：VLESS Reality、VLESS gRPC Reality、Trojan Reality、Hysteria2、VMess WebSocket、Hysteria2 Salamander、Shadowsocks 2022、Shadowsocks、TUIC v5、AnyTLS。内核固定为 `v1.13.7`。协议是否能被特定客户端使用仍受客户端支持影响；自签证书协议需要对应的证书校验设置。

## 可选 WARP（实验性）

仍在同一个容器，保留原来的 `127.0.0.1:40000` 通信。默认关闭：这样先验证 CentOS 7 上的直连节点，不把 WARP 的内核要求变成所有节点的启动条件。

在阅读并接受 [Cloudflare 条款](https://www.cloudflare.com/application/terms/) 后，将 `.env` 中三个值设为：

```dotenv
INSTALL_WARP=true
ENABLE_WARP=true
WARP_ACCEPT_TOS=true
```

然后 `docker compose up -d --build`。这会安装官方 WARP，保留注册信息，并增加 10 个 WARP 节点。WARP 初始化或出口检查失败会停止启动，不回退为直连。没有采用 `--privileged`，也不默认授予修改宿主网络的能力。

此版本尚未验证 WARP 在 CentOS 7、ARM64 上的运行条件。若提示内核、权限或设备不支持，请保留日志；先关闭 WARP 使用直连。不要直接为 host 网络容器增加 `NET_ADMIN` 或 privileged，这会允许修改宿主网络。官方本地代理的 UDP 目标支持也尚未验证；Hysteria2/TUIC 的 UDP 入站与 UDP 出站不是同一件事。

## 更新、备份与卸载

```bash
docker compose stop
tar -czf singdock-backup.tar.gz .env data
docker compose start
git pull --ff-only
docker compose up -d --build
```

备份含节点密钥和 WARP 身份，请限制访问。升级前记录 `git rev-parse HEAD`；失败时恢复旧提交重新构建，必要时在停止容器后恢复备份。首版不提供自动升级/自动同步上游。

`docker compose down` 停止并移除容器，挂载的数据仍保留。删除数据会丢失节点身份，确认备份后再手动处理。

## 故障排查

- 查看 `docker compose logs --tail=200` 与 `singdock status`。
- 配置错误：执行 `singdock check`；新配置校验通过才替换正在使用的文件。
- 无法连接：确认 `singdock ports` 输出、TCP/UDP 安全组、宿主防火墙及客户端协议支持。
- Debian 镜像出现 `Operation not permitted`：核对 Docker/containerd/libseccomp 版本，旧 Docker 的 seccomp 可能不支持新用户空间调用。优先更新运行时，首版不自动关闭 seccomp。
- Docker 共享宿主内核，CentOS 7 的 3.10 内核是否支持所需功能，必须在目标 VPS 实测；容器不能升级宿主内核。

## 上游与验证

详见 [UPSTREAM.md](UPSTREAM.md)。上游源码保持原结构，只有非终端保护与可导入入口两个适配；覆盖函数集中在 `docker/manage.sh`。不用每次启动从远程下载执行脚本。

本地验证：

```bash
docker build -t singdock:test .
bash tests/smoke.sh singdock:test bridge
bash tests/smoke.sh singdock:test host
```

CI 分别覆盖隔离 bridge 网络与部署使用的 host 网络，测试配置、错误配置不覆盖旧文件、密钥/证书/端口保留、停止、分享链接、端口更换，以及十种节点的客户端 → 代理 → HTTP 链路。TLS 测试显式信任生成的证书，保持证书校验开启。Reality 使用本地 TLS 1.3/H2 目标，客户端配置真实公钥、short ID、uTLS 和对应传输；不依赖公网 SNI 网站。Hysteria2/TUIC 的检查覆盖 UDP 入站传输到 TCP 目标，不代表 UDP 目标或 WARP 出站可用。

host 测试会临时监听测试机器端口，包括仅供本地 Reality 目标使用的 127.0.0.1:443，应在测试机器运行；脚本退出时清理自己的容器和测试数据。正常部署不会启动该 TLS 测试目标。测试结果不代表所有客户端或 WARP 均兼容。

## GUI 节点管理与自定义端口

保留上游脚本和已有节点凭据，新增一个随容器启动的轻量 Web 界面，无需单独数据库或 Docker socket。支持单节点端口编辑、连续端口批量分配、自定义端口列表、变更预览和分享链接。应用前检查端口范围、重复、占用和 sing-box 配置；重启失败会恢复旧配置并尝试恢复服务。服务重启会短暂断开连接。

已部署用户更新代码并在 `.env` 添加：

```dotenv
ENABLE_GUI=true
GUI_BIND=127.0.0.1
GUI_PORT=18100
GUI_PASSWORD=替换为至少16字符的独立强密码
```

```bash
git pull
docker compose up -d --build
```

默认 host 网络下，GUI 只监听 VPS 的本地回环地址。通过 SSH 隧道访问：

```bash
ssh -L 18100:127.0.0.1:18100 root@你的VPS地址
```

在本机打开 `http://127.0.0.1:18100`，用户名 `admin`，密码为 `GUI_PASSWORD`。也可以让宿主 Nginx 使用 HTTPS 反代 `http://127.0.0.1:18100`。请勿把 Basic 登录界面直接通过明文 HTTP 暴露公网；只有 HTTPS 反代或 SSH 隧道才能保护传输中的密码与分享链接。管理端口可用 `GUI_PORT` 自定义。GUI 默认关闭，不影响已有部署。

批量操作：勾选节点 → 选择连续端口或填写逗号分隔的端口列表 → 填入 → 预览变更 → 应用并重启。列表按界面中的所选节点顺序对应。支持 1024–65535；端口不允许重复，也不能使用管理端口或 WARP 保留的 40000。只对当前启用节点进行编辑；WARP 未开启时不会显示其节点。修改后请在 VPS 安全组和宿主防火墙放行新端口，并重新导入分享链接。bridge 网络用户还需同步修改 Docker 发布端口。

GUI 的节点列表不会返回密码、私钥或 UUID；分享链接仅在点击后读取，包含客户端连接凭据。配置、端口和回滚备份写在原有持久化数据目录，文件权限为 600。正常操作有文件锁保护和过期预览检测；配置替换与端口替换是两个写入步骤，过程中若容器被强制终止，请检查 `.bak` 备份后恢复。端口探测与实际重启之间仍可能发生外部端口抢占，重启失败会触发回滚。
