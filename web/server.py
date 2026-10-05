"""Authenticated Flask management API, served by Waitress without debug mode."""
import base64
import hmac
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from flask import Flask, Response, request, redirect
from werkzeug.exceptions import HTTPException
from waitress import create_server
from ports import PortManager
from settings import Settings
from http_security import LoginLimiter

ROOT = Path(__file__).parent
MAX_BODY = 16384


def create_app(settings=None, manager=None, links_provider=None):
    settings = settings or Settings.from_env()
    manager = manager or PortManager('/opt/sing-box', (settings.port, 40000))
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=MAX_BODY, DEBUG=False)
    app.json.ensure_ascii = False
    limiter = LoginLimiter()
    expected = b'Basic ' + base64.b64encode((settings.username + ':' + settings.password).encode())

    def reply(status, data):
        return app.json.response(data), status

    @app.after_request
    def secure_headers(response):
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if response.status_code == 401:
            response.headers['WWW-Authenticate'] = 'Basic realm="SingDock", charset="UTF-8"'
        if response.status_code == 429:
            response.headers['Retry-After'] = '60'
        return response

    @app.before_request
    def authenticate():
        # WSGI PATH_INFO is decoded. Match the raw URI too so encoded separators
        # cannot expose an alias of the private prefix. Waitress supplies REQUEST_URI.
        raw = request.environ.get('REQUEST_URI', request.environ.get('RAW_URI', request.path))
        path = urlsplit(raw).path
        prefix = settings.path
        if '%' in path or not path.startswith(prefix + '/'):
            if path == prefix and prefix and request.method == 'GET':
                return redirect(prefix + '/', code=308)
            return reply(404, {'error': '页面不存在'})
        valid = hmac.compare_digest(request.headers.get('Authorization', '').encode(), expected)
        status = limiter.authenticate(request.remote_addr or '', valid)
        if status != 200:
            return reply(status, {'error': '登录失败过多，请稍后再试' if status == 429 else '请使用配置的管理用户名和密码登录'})

    def read_links():
        result = subprocess.run(['singdock', 'links'], capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError('links unavailable')
        return result.stdout.decode()

    @app.get(settings.path + '/api/nodes')
    def nodes():
        try:
            return reply(200, manager.snapshot())
        except Exception:
            return reply(503, {'error': '读取失败，请检查容器状态'})

    @app.get(settings.path + '/api/links')
    def links():
        try:
            return reply(200, {'links': (links_provider or read_links)()})
        except Exception:
            return reply(503, {'error': '读取失败，请检查容器状态'})

    def change(apply):
        # This header forces cross-site browsers through a preflight; no CORS is enabled.
        if request.headers.get('X-SingDock-Request') != '1' or request.headers.get('Content-Type') != 'application/json':
            return reply(403, {'error': '请求来源校验失败'})
        if not request.content_length:
            return reply(400, {'error': '请求长度格式无效'})
        try:
            raw = request.get_data()
            if len(raw) != request.content_length:
                raise ValueError('请求未完整发送')
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError('请求格式无效')
            return reply(200, manager.change(body.get('ports'), body.get('revision'), apply))
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return reply(400, {'error': '端口或配置无效，请刷新并检查端口范围、重复和占用情况'})
        except ValueError as error:
            return reply(400, {'error': str(error)})
        except RuntimeError as error:
            return reply(409, {'error': str(error)})
        except HTTPException:
            raise
        except Exception:
            return reply(500, {'error': '操作失败，请检查容器日志'})

    app.add_url_rule(settings.path + '/api/preview', 'preview', lambda: change(False), methods=['POST'], provide_automatic_options=False)
    app.add_url_rule(settings.path + '/api/apply', 'apply', lambda: change(True), methods=['POST'], provide_automatic_options=False)

    def asset(name, kind):
        return Response((ROOT / name).read_bytes(), content_type=kind)

    for suffix, name, kind in [('/', 'index.html', 'text/html; charset=utf-8'),
                               ('/app.js', 'app.js', 'text/javascript; charset=utf-8'),
                               ('/style.css', 'style.css', 'text/css; charset=utf-8')]:
        app.add_url_rule(settings.path + suffix, name,
                         lambda name=name, kind=kind: asset(name, kind), methods=['GET'])

    @app.errorhandler(HTTPException)
    def http_error(error):
        return reply(error.code, {'error': '请求无效' if error.code != 404 else '页面不存在'})

    @app.errorhandler(Exception)
    def unexpected_error(_):
        return reply(500, {'error': '操作失败，请检查容器日志'})

    return app


def make_server(app, host, port):
    return create_server(app, host=host, port=port, threads=8,
                         connection_limit=32, backlog=32, channel_timeout=15,
                         cleanup_interval=5, max_request_body_size=MAX_BODY,
                         max_request_header_size=8192, expose_tracebacks=False,
                         log_socket_errors=False, clear_untrusted_proxy_headers=True)


def main():
    try:
        settings = Settings.from_env()
    except ValueError as error:
        raise SystemExit(str(error))
    server = make_server(create_app(settings), settings.bind, settings.port)
    host = '[' + settings.bind + ']' if ':' in settings.bind else settings.bind
    print(f'SingDock GUI: http://{host}:{settings.port}{settings.path}/', flush=True)
    print('GUI login details: docker exec singdock singdock gui-info', flush=True)
    server.run()


if __name__ == '__main__':
    main()
