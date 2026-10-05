"""Exercise authenticated HTTP preview/apply against the real running container."""
import base64
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

url = 'http://127.0.0.1:' + os.environ.get('GUI_PORT', '18100')
auth = 'Basic ' + base64.b64encode(('admin:' + os.environ['GUI_PASSWORD']).encode()).decode()


def request(path, body=None, authorized=True):
    headers = {'Authorization': auth} if authorized else {}
    if body is not None:
        headers.update({'Content-Type': 'application/json', 'X-SingDock-Request': '1'})
    with urlopen(Request(url + path, headers=headers,
                         data=json.dumps(body).encode() if body else None), timeout=60) as response:
        return json.load(response)


try:
    request('/api/nodes', authorized=False)
    raise AssertionError('Anonymous GUI access succeeded')
except HTTPError as error:
    assert error.code == 401
before = request('/api/nodes')
assert len(before['nodes']) == 10
ports = {node['tag']: node['port'] for node in before['nodes']}
changes = {'ss': ports['hy2'], 'hy2': ports['ss']}
body = {'ports': changes, 'revision': before['revision']}
assert not request('/api/preview', body)['applied']
assert request('/api/nodes') == before
assert request('/api/apply', body)['applied']
after = request('/api/nodes')
assert after['revision'] != before['revision']
for node in after['nodes']:
    assert node['port'] == changes.get(node['tag'], ports[node['tag']])
try:
    request('/api/apply', body)
    raise AssertionError('Stale preview accepted')
except HTTPError as error:
    assert error.code == 400
links = request('/api/links')['links']
assert '-warp' not in links
assert f":{changes['hy2']}?" in links
assert request('/api/apply', {'ports': {'ss': ports['ss'], 'hy2': ports['hy2']},
                              'revision': after['revision']})['applied']
print('PASS: GUI authentication, preview, real restart, persistence, stale preview and share links')
