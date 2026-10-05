# SingDock

**用 Docker 一次部署 10 个代理节点，在网页里查看、改端口、复制连接链接。**

适合已有 Linux VPS 的用户，也可在 CentOS 7 上运行。基于 [Sing-Box-Plus](https://github.com/Alvin9999-newpac/Sing-Box-Plus)，无需额外数据库。

- 支持 Reality、Hysteria2、Shadowsocks、VMess、TUIC、AnyTLS 等协议。
- 支持电脑和手机；单个或批量修改端口，应用前预览，失败时恢复旧配置。
- 自动生成管理密码和随机访问路径，也能自己设置。
- 重启和重新构建保留已有节点、端口、证书和登录信息。

## 页面截图

以下为使用合成节点的真实浏览器截图。

![桌面节点管理](docs/screenshots/desktop.png)

<details>
<summary>查看端口预览和手机截图</summary>

![端口变更预览](docs/screenshots/port-preview.png)

<img src="docs/screenshots/mobile.png" alt="手机节点管理" width="390">

</details>

## 1. 安装并启动

准备一台已安装 **Docker 和 Docker Compose** 的 Linux VPS。在 VPS 的 SSH 终端执行：

```bash
git clone https://github.com/While-Shark/SingDock.git
cd SingDock
cp .env.example .env
nano .env
```

修改下面两项，其他保持默认。密码留空即可自动生成：

```dotenv
PUBLIC_HOST=你的VPS公网IP或域名
ENABLE_GUI=true
GUI_PASSWORD=
GUI_PATH=auto
```

保存后启动，首次构建需要几分钟：

```bash
chmod 600 .env
docker compose up -d --build
```

## 2. 打开管理页面

等容器启动后，在 VPS 上查看地址、用户名和密码：

```bash
docker compose exec singdock singdock gui-info
```

默认用户名是 `admin`。自动密码共 32 位，含大小写字母、数字和符号；密码不会打印到启动日志中。

**用面板反代访问：** 在宝塔、1Panel 等面板添加反向代理，目标地址填写 `http://127.0.0.1:18100`，代理目录为 `/`，开启域名 HTTPS。访问时将 `gui-info` 显示地址的 `http://127.0.0.1:18100` 换成你的 HTTPS 域名，保留完整随机路径，例如 `https://你的域名/panel-随机字符串/`。保持 `GUI_BIND=127.0.0.1`，无需对外开放 `18100` 端口。

**不用域名也能访问：** 在**你自己的电脑**新开一个终端，执行下面的命令，并保持窗口打开：

```bash
ssh -L 18100:127.0.0.1:18100 root@你的VPS公网IP
```

然后在电脑浏览器打开 `gui-info` 显示的地址，例如 `http://127.0.0.1:18100/panel-随机字符串/`，输入显示的用户名和密码。不要将登录信息发给他人。

## 3. 使用节点

在网页里点击“分享链接”，复制后导入支持对应协议的客户端。如果客户端提示证书问题，请按客户端说明配置信任。

查看需要放行的端口：

```bash
docker compose exec singdock singdock ports
```

按输出在 VPS 安全组和防火墙中放行对应 TCP/UDP 端口。网页改端口后，也要更新放行规则和客户端链接。

## 已部署？这样更新

先备份 `.env` 和 `data` 目录，再在原来的项目目录执行：

```bash
git pull --ff-only
docker compose up -d --build
```

**保留 `data` 目录，已有节点就会保留。** 更新会短暂断开连接，完成后重新连接即可。旧部署设置了密码或路径时仍使用原值；想自动生成密码就将 `GUI_PASSWORD` 留空，随机入口设为 `GUI_PATH=auto`。

## 常见操作

| 想做什么 | 在 VPS 上执行 |
| --- | --- |
| 忘记管理地址或密码 | `docker compose exec singdock singdock gui-info` |
| 查看启动日志 | `docker compose logs --tail=100 singdock` |
| 查看节点连接链接 | `docker compose exec singdock singdock links` |
| 打开原版中文菜单 | `docker compose exec singdock singdock menu` |

自定义账号/端口、备份、重新生成密码、WARP 和故障排查见[进阶说明](docs/ADVANCED.md)。WARP 仍为实验性功能；安全修复及限制见 [SECURITY.md](SECURITY.md)。
