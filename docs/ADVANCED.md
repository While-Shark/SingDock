# SingDock 进阶配置

[返回快速入门](../README.md)

## 手机与 HTTPS 访问

手机可用支持本地端口转发的 SSH 客户端，将手机的 `18100` 转发到 VPS 的 `127.0.0.1:18100`，保持连接后在手机浏览器打开管理地址。

需要直接通过域名访问时，让宿主 Nginx 在 HTTPS 站点内反代到 `http://127.0.0.1:18100`，保留完整路径。以下仅为已有 HTTPS 站点中的反代片段，域名和证书由你的面板或 Nginx 管理：

```nginx
location / {
    proxy_pass http://127.0.0.1:18100;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

不要剥离随机路径前缀。Basic 登录需要 SSH 隧道或 HTTPS；不要直接在公网用 HTTP 传输密码。监听所有地址时，`gui-info` 显示的 `0.0.0.0` / `::` 是监听地址，浏览器请使用实际域名或 SSH 隧道地址。

## 备份

在项目目录执行，备份包含所有节点和管理登录信息：

```bash
umask 077
docker compose stop
tar -czf "singdock-backup-$(date +%Y%m%d-%H%M%S).tar.gz" .env data
docker compose start
```

妥善保存备份。更新时保留原数据挂载，不要将 `data` 替换成空目录。

## GUI 配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `ENABLE_GUI` | `false` | 是否启动 GUI |
| `GUI_BIND` | `127.0.0.1` | IPv4/IPv6 监听地址；默认不向公网直接开放 |
| `GUI_PORT` | `18100` | 管理端口，1024–65535；不可使用 WARP 保留的 40000 |
| `GUI_USERNAME` | `admin` | 1–64 个字符，可使用中文；不可含冒号、控制字符或首尾空白 |
| `GUI_PASSWORD` | 自动生成 | 留空时生成并保存 32 位复杂密码；手动设置需 16–256 个字符，不可含控制字符，可含冒号 |
| `GUI_PATH` | `auto` | 留空或设为 `auto` 自动生成；也可指定 `/private/control`、`/` 等路径 |
| `PUBLIC_HOST` | 自动检测 | VPS 公网 IP 或域名，建议显式填写以确保分享链接正确 |

路径末尾 `/` 可省略，访问时会自动补齐。设置自定义路径后，原来的 `/`、`/api/*` 和静态资源入口不再提供 GUI。路径不替代登录保护。

随机路径保存在 `data/sing-box/gui-path`，权限为 `600`。重启、重建镜像和重新创建容器均沿用此路径，备份数据目录时一并备份。显式指定 `GUI_PATH` 会覆盖本次使用的路径；恢复 `auto` 后继续使用原随机路径。旧部署明确配置 `GUI_PATH=/` 时仍使用根路径；未设置或留空会改用随机入口。

修改配置后执行 `docker compose up -d --build`，已有节点凭据会保留。如需重新生成随机入口，先停止容器，删除 `data/sing-box/gui-path`，保持 `GUI_PATH=auto` 后启动。若路径文件损坏或是符号链接，启动会拒绝使用，请检查或删除该文件再重建；不会静默退回根路径。

### 自动密码与找回登录信息

密码留空时，首次启用 GUI 会生成一个包含大小写字母、数字和符号的 32 位密码，保存到 `data/sing-box/gui-password`，权限为 `600`。重启、重建和重新创建容器继续使用原密码。查看登录信息：

```bash
docker compose exec singdock singdock gui-info
```

此命令只在本地显示信息，不会写入启动日志，也不会创建或重置缺失的状态文件。GUI 未启用时会提示先启用。请勿将命令输出、`.env` 或数据目录发给他人。

填写 `GUI_PASSWORD` 会使用手动密码；重新留空会恢复原来的自动密码。要更换自动密码，先 `docker compose stop`，删除 `data/sing-box/gui-password`，保持密码留空，再 `docker compose up -d --build`。节点密码不会随管理密码改变。若状态文件损坏，先检查或备份文件，再按此步骤重建，不会静默使用新密码。

### 修改节点端口

1. 勾选节点，选择连续端口或填写逗号分隔的端口列表；列表按界面中的所选节点顺序对应。
2. 点击“填入所选节点”，也可直接逐行编辑新端口。
3. 点击“预览变更”，检查新旧端口，再“应用并重启”。
4. 放行 VPS 防火墙/安全组，获取新分享链接并更新客户端。

端口范围为 1024–65535，不允许重复或使用 GUI/WARP 保留端口。WARP 未开启时只显示直连节点。应用会短暂断开连接；bridge 网络用户还需同步修改 Docker 发布端口。

<details>
<summary>命令行管理与全部协议</summary>

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

包含 VLESS Reality、VLESS gRPC Reality、Trojan Reality、Hysteria2、VMess WebSocket、Hysteria2 Salamander、Shadowsocks 2022、Shadowsocks、TUIC v5、AnyTLS。内核固定为 `v1.13.7`，客户端需要支持所选协议。自签名证书协议需按客户端要求配置信任。BBR 在宿主机设置，容器不修改宿主 systemd。

</details>

<details>
<summary>可选 WARP（实验性）</summary>

在阅读并接受 [Cloudflare 条款](https://www.cloudflare.com/application/terms/) 后，在 `.env` 设置：

```dotenv
INSTALL_WARP=true
ENABLE_WARP=true
WARP_ACCEPT_TOS=true
```

执行 `docker compose up -d --build`。WARP 在同一容器内通过 `127.0.0.1:40000` 提供代理，注册信息持久化。初始化或出口检查失败会停止启动，不回退为直连。

AMD64/ARM64 的 WARP 镜像构建及二进制检查已通过；注册、连接、CentOS 7/ARM64 上的实际出口及 UDP 目标仍需实测。不要直接给 host 网络容器增加 `NET_ADMIN` 或 privileged。

</details>

<details>
<summary>验证、故障排查与实现边界</summary>

- [Container CI](https://github.com/While-Shark/SingDock/actions/workflows/container.yml)：AMD64/ARM64、bridge/host，检查启动、凭据/随机路径持久化、启动日志、GUI 登录、预览、真实服务重启和 10 种节点的客户端 → 代理 → HTTP 链路。Reality 使用隔离的本地 TLS 1.3/H2 目标。
- [GUI Browser CI](https://github.com/While-Shark/SingDock/actions/workflows/gui-browser.yml)：1280px 桌面和 390px 手机，覆盖批量配置、取消/应用预览、过期配置错误、链接复制和关闭清理；覆盖显式根路径/默认账号与自定义路径/账号两组测试。合成节点截图保存在 `gui-browser-screenshots-*` 产物中，保留 7 天。
- 持久化节点设置通过白名单数据解析，不执行 `source`；可写数据目录不进入执行 PATH。GUI 对登录失败限流，通过 Waitress 限制线程、连接、请求头和请求体，拒绝冲突请求长度。反代下限流按实际连接地址计数，不信任可伪造的转发头。
- GUI 列表不返回密码、私钥或 UUID；分享链接含客户端凭据，按需读取。界面不需要 Docker socket，包含登录校验、跨站写入拦截、文件锁、过期预览检测和静态文件白名单。
- 配置及回滚备份使用 600 权限。端口/配置分别原子替换；强制终止容器可能需要用 `.bak` 恢复。探测与重启间的端口抢占会由失败回滚处理。
- 查看 `docker compose logs --tail=200` 和 `singdock status`；配置问题执行 `singdock check`。
- CentOS 7 用户已实测 VLESS 连通。Docker 共享宿主内核，其他协议/WARP 在目标 VPS 的可用性仍受内核、Docker/containerd/libseccomp 和客户端支持影响。优先更新旧运行时，不自动关闭 seccomp。
- SELinux 挂载使用 `:Z`，数据目录供单个容器使用，不与多个副本共享。
- 后端测试：先用 Python 3.11+ 创建虚拟环境并 `pip install -r requirements.txt`，再运行 `python -m unittest discover -s tests -p 'test_*.py' -v`。容器自动安装锁定依赖，并通过 Supervisor 启动 Waitress；不使用 Flask 开发服务器。
- 完整本地测试：`docker build -t singdock:test .` 后运行 `bash tests/smoke.sh singdock:test bridge` 或 `host`。host 测试临时使用本机端口及 `127.0.0.1:443`，请在测试机器运行。

上游信息与适配方式见 [UPSTREAM.md](../UPSTREAM.md)。不在每次启动时下载执行远程脚本，不自动同步上游；升级前可记录 `git rev-parse HEAD` 以便回退。

</details>

安全扫描范围、修复和剩余边界见 [SECURITY.md](../SECURITY.md)。
