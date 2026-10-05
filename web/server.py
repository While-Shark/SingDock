"""Small authenticated management surface; no Docker socket or shell input."""
import base64
import hmac
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from ports import PortManager
from settings import Settings
from http_security import BoundedHTTPServer

ROOT = Path(__file__).parent


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log credentials, bodies, or share links.

    def send(self, status, data, kind='application/json; charset=utf-8'):
        raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if status == 429:
            self.send_header('Retry-After', '60')
        if status == 401:
            self.send_header('WWW-Authenticate', 'Basic realm="SingDock", charset="UTF-8"')
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        token = base64.b64encode((self.server.username + ':' + self.server.password).encode()).decode()
        return hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Basic ' + token).encode())

    def require_auth(self):
        status = self.server.login_limiter.authenticate(self.client_address[0], self.authorized())
        if status != 200:
            self.send(status, {'error': '登录失败过多，请稍后再试' if status == 429 else '请使用配置的管理用户名和密码登录'})
            return False
        return True

    def route(self):
        """Match the configured prefix exactly, before issuing an auth challenge."""
        try:
            path = urlsplit(self.path).path
        except ValueError:
            return None
        prefix = self.server.gui_path
        if prefix and path == prefix:
            return ''
        if path.startswith(prefix + '/'):
            return path[len(prefix):]
        return None

    def do_GET(self):
        path = self.route()
        if path is None:
            return self.send(404, {'error': '页面不存在'})
        if path == '':
            # Relative assets and API calls need the canonical trailing slash.
            self.send_response(308)
            self.send_header('Location', self.server.gui_path + '/')
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        if not self.require_auth():
            return
        try:
            if path == '/api/nodes':
                return self.send(200, self.server.manager.snapshot())
            if path == '/api/links':
                result = subprocess.run(['singdock', 'links'], capture_output=True, timeout=30)
                if result.returncode:
                    raise RuntimeError('节点链接获取失败，请检查 PUBLIC_HOST')
                return self.send(200, {'links': result.stdout.decode()})
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in assets:
                name, kind = assets[path]
                return self.send(200, (ROOT / name).read_bytes(), kind)
            self.send(404, {'error': '页面不存在'})
        except Exception:
            self.send(503, {'error': '读取失败，请检查容器状态'})

    def do_POST(self):
        path = self.route()
        if path not in ('/api/preview', '/api/apply'):
            return self.send(404, {'error': '接口不存在'})
        if not self.require_auth():
            return
        # Custom header forces cross-site requests through a preflight we do not allow.
        if self.headers.get('X-SingDock-Request') != '1' or self.headers.get('Content-Type') != 'application/json':
            return self.send(403, {'error': '请求来源校验失败'})
        if self.headers.get('Transfer-Encoding') is not None or len(self.headers.get_all('Content-Length', [])) != 1:
            return self.send(400, {'error': '请求长度格式无效'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError('请求大小无效')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('请求未完整发送')
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError('请求格式无效')
            result = self.server.manager.change(body.get('ports'), body.get('revision'), path == '/api/apply')
            self.send(200, result)
        except (json.JSONDecodeError, TypeError):
            self.send(400, {'error': '端口或配置无效，请刷新并检查端口范围、重复和占用情况'})
        except ValueError as error:
            self.send(400, {'error': str(error)})
        except RuntimeError as error:
            self.send(409, {'error': str(error)})
        except Exception:
            self.send(500, {'error': '操作失败，请检查容器日志'})

    def setup(self):
        super().setup()
        self.connection.settimeout(15)


def main():
    try:
        settings = Settings.from_env()
    except ValueError as error:
        raise SystemExit(str(error))
    server = BoundedHTTPServer((settings.bind, settings.port), Handler)
    server.username = settings.username
    server.password = settings.password
    server.gui_path = settings.path
    server.manager = PortManager('/opt/sing-box', (settings.port, 40000))
    server.serve_forever()


if __name__ == '__main__':
    main()
