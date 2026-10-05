'use strict';
const $ = id => document.getElementById(id);
let snapshot, pending, busy = false;
function notice(text, error = false) {
  $('notice').textContent = text; $('notice').className = error ? 'error' : '';
  const dialog = document.querySelector('dialog[open] .dialog-notice');
  if (dialog) { dialog.textContent = text; dialog.classList.toggle('error', error); }
}
async function api(path, body) {
  const response = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json','X-SingDock-Request':'1'}, body:JSON.stringify(body)} : {});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '请求失败');
  return data;
}
async function action(fn) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  try { await fn(); } catch (e) { notice(e.message, true); }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); }
}
async function refresh() {
  snapshot = await api('api/nodes'); pending = null;
  $('count').textContent = snapshot.nodes.length;
  $('nodes').replaceChildren(); $('all').checked = false;
  for (const node of snapshot.nodes) {
    const row = document.createElement('tr'); row.dataset.tag = node.tag;
    const cell = () => row.appendChild(document.createElement('td'));
    const check = document.createElement('input'); check.type = 'checkbox'; check.setAttribute('aria-label', `选择 ${node.tag}`); cell().append(check);
    const title = cell(); title.textContent = node.tag; const small = document.createElement('small'); small.textContent = node.type; title.append(small);
    cell().textContent = node.warp ? 'WARP' : '直连'; cell().textContent = node.network; cell().textContent = node.port;
    const input = document.createElement('input'); input.type = 'number'; input.min = 1024; input.max = 65535; input.value = node.port; input.setAttribute('aria-label', `${node.tag} 新端口`); cell().append(input);
    $('nodes').append(row);
  }
  notice('配置已加载。修改后先预览，再应用。');
}
$('refresh').onclick = () => action(refresh);
$('all').onchange = () => document.querySelectorAll('#nodes input[type=checkbox]').forEach(c => c.checked = $('all').checked);
$('mode').onchange = () => { const list = $('mode').value === 'list'; $('port-label').textContent = list ? '端口列表（按所选节点顺序）' : '起始端口'; $('batch-ports').placeholder = list ? '20000, 20010, 20020' : '20000'; };
$('assign').onclick = () => action(async () => {
  const rows = [...document.querySelectorAll('#nodes tr')].filter(r => r.querySelector('[type=checkbox]').checked);
  if (!rows.length) throw Error('请先选择节点');
  const raw = $('batch-ports').value.trim();
  const values = $('mode').value === 'list' ? raw.split(/[\s,，]+/).map(v => /^\d+$/.test(v) ? Number(v) : NaN) : rows.map((_, i) => /^\d+$/.test(raw) ? Number(raw) + i : NaN);
  if (values.length !== rows.length || values.some(v => !Number.isInteger(v) || v < 1024 || v > 65535)) throw Error('请填写有效端口，列表数量需与所选节点相同');
  rows.forEach((r, i) => r.querySelector('[type=number]').value = values[i]); notice('已填入，请预览变更。');
});
$('preview').onclick = () => action(async () => {
  if (!snapshot) throw Error('请先刷新配置');
  const ports = {};
  for (const row of document.querySelectorAll('#nodes tr')) {
    const original = snapshot.nodes.find(n => n.tag === row.dataset.tag).port;
    const input = row.querySelector('[type=number]'); if (!input.checkValidity() || !input.value) throw Error('端口必须是 1024–65535 的整数');
    const value = Number(input.value); if (value !== original) ports[row.dataset.tag] = value;
  }
  if (!Object.keys(ports).length) throw Error('尚未修改端口');
  pending = {ports, revision:snapshot.revision};
  const result = await api('api/preview', pending); $('changes').replaceChildren();
  for (const change of result.changes) { const row = document.createElement('div'); row.className = 'change'; const name = document.createElement('span'); name.textContent = change.tag; const value = document.createElement('strong'); value.textContent = `${change.before} → ${change.after}`; row.append(name, value); $('changes').append(row); }
  $('confirmation-notice').textContent = ''; $('confirmation').showModal();
});
$('cancel').onclick = () => $('confirmation').close();
$('apply').onclick = () => action(async () => { const result = await api('api/apply', pending); $('confirmation').close(); await refresh(); notice(result.applied ? '端口已应用，服务已重启。请放行防火墙并更新客户端链接。' : '没有需要应用的变更。'); });
$('links').onclick = () => action(async () => { $('share-text').value = (await api('api/links')).links; $('share-notice').textContent = ''; $('share').showModal(); });
$('close-share').onclick = () => $('share').close();
$('share').addEventListener('close', () => { $('share-text').value = ''; });
$('copy').onclick = () => action(async () => { await navigator.clipboard.writeText($('share-text').value); notice('分享链接已复制。'); });
action(refresh);
