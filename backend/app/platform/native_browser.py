"""Local attended browser provider. Native website networking; platform approves inputs.

Only fixed, internally authored observation functions reach browser_evaluate.
No arbitrary script, selector, upstream tool or host file path is exposed to the model.
"""
import asyncio
import logging
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

from app.errors import ServiceError
from app.platform.browser import BrowserService, BROWSER_DIRECTORY, CLOSE_KEYS, origin, readback_row
from app.platform.browser_dom import ELEMENT_INFO_JS, HELPERS
from app.platform.native_mcp import NativeMcp, CLI, MCP_VERSION, result_json, result_text
from app.platform.form_engine import McpDriver

logger = logging.getLogger(__name__)

EMPTY_IMAGE = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
META_JS = '() => ({url:location.href,title:document.title,viewport:{width:innerWidth,height:innerHeight},visible:!!document.body?.innerText.trim(),ready_state:document.readyState,body_characters:document.body?.innerText.length||0,frame_count:document.querySelectorAll("iframe").length})'
FINGERPRINT_JS = '() => {' + HELPERS + '''return {url:location.href,fields:collect().map(e=>({id:e.id,name:e.name,...info(e),
    checked:['checkbox','radio'].includes(e.type)?e.checked:undefined,
    files:e.type==='file'?Array.from(e.files||[]).map(f=>({name:f.name,size:f.size,lastModified:f.lastModified})):undefined}))};}'''


def semantic_snapshot(text):
    """Ignore observation IDs/focus styling, preserving text and meaningful state.

    Only strip attributes in the YAML node header; never strip matching strings
    from user-visible text, quoted accessible names, URLs or field values.
    """
    header = re.compile(r'^(\s*- [\w-]+(?: "(?:[^"\\]|\\.)*")?)(?P<attrs>(?: \[[^\]\n]*\])*)(?P<tail>.*)$')
    noise = re.compile(r' \[(?:ref=[a-zA-Z0-9]+|active|cursor=pointer)\]')
    lines = []
    for line in text.splitlines():
        match = header.match(line)
        lines.append(match[1] + noise.sub('', match['attrs']) + match['tail'] if match else line)
    return '\n'.join(lines)


def snapshot_body(text):
    match = re.search(r'### Snapshot\s+```yaml\n(.*?)\n```', text, re.S)
    if not match:
        raise ServiceError('未取得可解析的页面快照，不能据此判断网页空白或登录状态。', 502)
    return match.group(1)


def browser_tabs(text):
    rows = []
    for line in text.splitlines():
        match = re.match(r'^- (\d+):( \(current\))? \[(.*)\]\((.*)\)(?: \[crashed\])?$', line)
        if match:
            index, current, title, url = match.groups()
            rows.append({'index': int(index), 'current': bool(current), 'title': title, 'url': url})
    return rows


def tab_summaries(tabs):
    # Login redirect query strings may contain authentication material.
    return [{**tab, 'url': urlunsplit(urlsplit(tab['url'])._replace(query='', fragment=''))} for tab in tabs]


def snapshot_elements(text):
    """Keep upstream refs and surrounding field labels; never fabricate CSS targets."""
    elements, label_at = [], {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'(\s*)- (\w+)(?: "((?:[^"\\]|\\.)*)")?.*?\[ref=([a-zA-Z0-9]+)\](.*)', line)
        if not match:
            continue
        indent, role, quoted, ref, tail = match.groups()
        depth = len(indent)
        for key in list(label_at):
            if key > depth:
                del label_at[key]
        label = json.loads('"' + quoted + '"') if quoted else tail.partition(':')[2].strip().strip('"')
        pointer = '[cursor=pointer]' in tail
        if role == 'generic' and not label and pointer:
            # Upload/drop zones often have no own accessible name. Their text
            # lives under an image/text child, including inside framed forms.
            descendants = []
            for child_index in range(index + 1, len(lines)):
                child = lines[child_index]
                if len(child) - len(child.lstrip()) <= depth:
                    break
                child_text = re.match(r'\s*- text: (.*)', child)
                if child_text:
                    descendants.append(child_text[1])
                if sum(map(len, descendants)) >= 250:
                    break
            label = ' '.join(descendants)[:250] or '可点击控件'
        if role == 'generic' and label and len(label) <= 100:
            label_at[depth] = label
        context = next((label_at[d] for d in sorted(label_at, reverse=True) if label_at[d] and not label_at[d].isdigit()), '')
        if role not in ('textbox', 'combobox', 'spinbutton', 'button', 'link', 'checkbox', 'radio', 'generic'):
            continue
        if role == 'generic' and (not label or len(label) > 250):
            continue
        if role in ('textbox', 'combobox', 'spinbutton') and (not label or label in ('请输入', '请选择')):
            label = context or label or '输入项'
        elements.append({'id': 'e_' + ref, 'native_ref': ref, 'label': label[:250], 'role': role,
                         'tag': {'textbox': 'input', 'combobox': 'select', 'button': 'button', 'link': 'a',
                                 'checkbox': 'input', 'radio': 'input'}.get(role, 'div'),
                         'clickable': role not in ('textbox', 'spinbutton'), 'pointer': pointer, 'disabled': '[disabled]' in line})
    # Form labels are generic nodes too. Keep real controls ahead of decorative
    # text so a long form's submit/attachment controls are not displaced by labels.
    return sorted(elements, key=lambda element: element['role'] == 'generic' and not element['pointer'])


def snapshot_page(page, options):
    """Bound each tool result, not the underlying snapshot or reference map."""
    text, elements = page['text'], page['elements']
    page_text_total, page_element_total = len(text), len(elements)
    query = (options.get('query') or '').strip()
    if query:
        needle = query.casefold()
        elements = [e for e in elements if needle in (e['label'] + ' ' + e['native_ref'] + ' ' + e['role']).casefold()]
        lines = text.splitlines(keepends=True)
        indices = set()
        for i, line in enumerate(lines):
            if needle in line.casefold():
                indices.update(range(max(0, i - 2), min(len(lines), i + 4)))
        text = ''.join(line for i, line in enumerate(lines) if i in indices)
    offset, limit = options.get('text_offset', 0), options.get('text_limit', 12000)
    element_offset, element_limit = options.get('element_offset', 0), options.get('element_limit', 80)
    for value, low, high in ((offset, 0, 10000000), (limit, 1, 20000), (element_offset, 0, 1000000), (element_limit, 1, 200)):
        if type(value) is not int or not low <= value <= high:
            raise ServiceError('页面分页参数无效。', 422)
    return {**page, 'text': text[offset:offset + limit], 'elements': elements[element_offset:element_offset + element_limit],
            'text_offset': offset, 'text_total': len(text), 'page_text_total': page_text_total,
            'text_truncated': offset > 0 or offset + limit < len(text),
            'next_text_offset': offset + limit if offset + limit < len(text) else None,
            'element_offset': element_offset, 'element_total': len(elements), 'page_element_total': page_element_total,
            'elements_truncated': element_offset > 0 or element_offset + element_limit < len(elements),
            'next_element_offset': element_offset + element_limit if element_offset + element_limit < len(elements) else None,
            'query': query or None,
            'read_hint': '完整快照已保留。查找上传/字段可用 browser_read(session_id, snapshot_id, query="上传")；继续分页传相同 snapshot_id 和 next_text_offset/next_element_offset，读取不会刷新快照或执行操作。新读页面不要传 snapshot_id。'}


class NativeBrowserService(BrowserService):
    def __init__(self, files, **kwargs):
        super().__init__(files, **kwargs)
        self.profile_root = BROWSER_DIRECTORY / 'native-profiles'

    def status(self):
        return {'provider': 'native_mcp', 'browser_name': 'Google Chrome · Playwright MCP',
                'available': CLI.is_file() and bool(shutil.which('node')), 'headed': not self.headless,
                'version': MCP_VERSION, 'manual_refresh_only': True,
                'message': '本机专用配置保留登录；网站正常联网；Agent 输入、上传和点击仍需确认。'}

    async def _dispatch(self, method, conversation_id, *args):
        if method not in {'open', 'read', 'prepare', 'execute', 'list', 'close', 'takeover', 'preview', 'form_extract',
                          'capture', 'screenshot', 'reload', 'observe', 'connection_list', 'connection_allow', 'connection_revoke'}:
            raise ServiceError('浏览器操作未开放。', 403)
        try:
            if method == 'preview':
                return await self._preview(conversation_id, *args)
            return await super()._dispatch(method, conversation_id, *args)
        except ServiceError as error:
            sid = args[0] if args and isinstance(args[0], str) else None
            session = self.sessions.get(sid)
            if error.status_code == 410 and session and session['conversation_id'] == conversation_id:
                await self._close(conversation_id, sid)
            raise

    async def _session(self, conversation_id, session_id):
        session = self.sessions.get(session_id)
        if not session or session['conversation_id'] != conversation_id:
            raise ServiceError('浏览器会话不存在或不属于当前对话。', 404)
        return session

    async def _open(self, conversation_id, url):
        self.validate_url(url)
        for session in self.sessions.values():
            if session['conversation_id'] == conversation_id:
                self._idle(session)
                await self._meta(session)
                # A continuation must never destroy an attended form to get back
                # to its old job URL. Opening the exact live URL only reviews it.
                if session['url'] == url and origin(url) != session['origin']:
                    session.update(origin=origin(url), snapshot_id='')
                page = await self._read(conversation_id, session['id'])
                if page['url'] != url:
                    page['warning'] = '复用了当前页面，没有跳转到请求的新地址。不要关闭或重开用户登录后的页面；先核对当前页面与标签。'
                return page
        if len(self.sessions) >= 4:
            raise ServiceError('最多保留四个专用浏览器，请先关闭不用的窗口。', 429)
        sid = 'browser_' + uuid4().hex
        directory = self.profile_root / hashlib.sha256(conversation_id.encode()).hexdigest()
        client = NativeMcp(directory, self.headless)
        session = {'id': sid, 'conversation_id': conversation_id, 'client': client, 'directory': directory,
                   'origin': origin(url), 'url': url, 'title': '', 'viewport': {'width': 1280, 'height': 720},
                   'manual_until': 0, 'writes': False, 'snapshot_id': '', 'handles': {}, 'lock': asyncio.Lock(),
                   'browser_name': 'Google Chrome · Playwright MCP', 'touched': time.time()}
        self.sessions[sid] = session
        try:
            await client.call('browser_navigate', {'url': url})
            return await self._read(conversation_id, sid)
        except Exception:
            self.sessions.pop(sid, None)
            await client.close()
            raise

    def _idle(self, session):
        if session['writes'] or time.time() < session['manual_until']:
            raise ServiceError('用户正在接手或页面正在执行操作，请交回后继续。', 409)

    async def _meta(self, session):
        value = result_json(await session['client'].call('browser_evaluate', {'function': META_JS}))
        session.update({k: value[k] for k in ('url', 'title', 'viewport')})
        return value

    async def _tabs(self, session):
        tabs = browser_tabs(result_text(await session['client'].call('browser_tabs', {'action': 'list'})))
        session['tabs'] = tab_summaries(tabs)
        return tabs

    async def _select_tab(self, session, tabs, index):
        tab = next((t for t in tabs if t['index'] == index), None)
        if type(index) is not int or not tab:
            raise ServiceError('标签已变化或不存在，请重新读取标签列表。', 409)
        if not tab['url'].startswith(('http://', 'https://')):
            raise ServiceError('所选标签不是网页，请选择已有的目标网页标签。', 409)
        if origin(tab['url']) != session['origin']:
            self.validate_url(tab['url'])
        await session['client'].call('browser_tabs', {'action': 'select', 'index': index})
        session.update(origin=origin(tab['url']), snapshot_id='', handles={})
        return await self._meta(session)

    async def _unready(self, session, meta, state):
        session.update(snapshot_id='', handles={}, page_state=state)
        diagnostics = {k: meta[k] for k in ('ready_state', 'body_characters', 'frame_count') if k in meta}
        if meta['url'].startswith(('http://', 'https://')):
            try:
                network = result_text(await session['client'].call('browser_network_requests', {'static': True}))
                failures = []
                for line in network.splitlines():
                    match = re.search(r'\[(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\]\s+(https?://\S+)\s+=>\s+\[?(\d{3}|FAILED)\]?', line)
                    if match and (match[3] == 'FAILED' or int(match[3]) >= 400):
                        code = re.search(r'net::ERR_[A-Z_]+', line)
                        failures.append({'host': urlsplit(match[2]).hostname, 'status': match[3],
                                         **({'error': code[0]} if code else {})})
                diagnostics['failed_resources'] = failures[-12:]
            except ServiceError:
                diagnostics['network_diagnostics'] = 'unavailable'
        return {'session_id': session['id'], 'provider': 'native_mcp', 'url': meta['url'], 'title': meta['title'],
                'snapshot_id': '', 'text': '', 'elements': [], 'elements_truncated': False,
                'page_state': state, 'authentication_state': 'unknown', 'tabs': session.get('tabs', []),
                'diagnostics': diagnostics,
                'notice': '没有取得可操作页面，不能据此判断未登录、已提交或 SPA 加载。先核对 tabs，使用 browser_read 的 tab_index 读取已有标签；不要关闭或重开页面。只询问确实无法核对的那一步，不要求用户手动完成整个任务。'}

    async def _inspect(self, session):
        meta = await self._meta(session)
        if origin(meta['url']) != session['origin']:
            raise ServiceError('页面已离开已核对的网站，请在浏览器管理重新打开并核对。', 409)
        snap = snapshot_body(result_text(await session['client'].call('browser_snapshot')))
        fields = result_json(await session['client'].call('browser_evaluate', {'function': FINGERPRINT_JS}))
        fingerprint = hashlib.sha256(json.dumps([meta['url'], semantic_snapshot(snap), fields], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return meta, snap, fingerprint

    async def _read(self, conversation_id, session_id, tab_index=None, options=None):
        session = await self._session(conversation_id, session_id)
        self._idle(session)
        options = options or {}
        if options.get('snapshot_id'):
            cached = session.get('read_snapshot')
            if tab_index is not None:
                raise ServiceError('翻页时不能同时切换标签，请先读取新标签。', 422)
            if not cached or options['snapshot_id'] != session['snapshot_id'] or options['snapshot_id'] != cached['snapshot_id']:
                raise ServiceError('快照已失效，请重新读取当前页面；不能混用旧页面引用。', 409)
            return snapshot_page(cached, options)
        meta = await self._meta(session)
        tabs = await self._tabs(session)
        if tab_index is not None:
            meta = await self._select_tab(session, tabs, tab_index)
            tabs = await self._tabs(session)
        elif meta['url'] == 'about:blank':
            candidates = [t for t in tabs if t['url'].startswith(('http://', 'https://')) and origin(t['url']) == session['origin']]
            if len(candidates) == 1:
                meta = await self._select_tab(session, tabs, candidates[0]['index'])
                tabs = await self._tabs(session)
            else:
                return await self._unready(session, meta, 'choose_tab' if tabs else 'blank')
        if origin(meta['url']) != session['origin']:
            session.update(snapshot_id='', handles={})
            raise ServiceError('当前标签已跳转。先查询会话当前网址，用 browser_read(tab_index) 选择已列出的网页标签，或 browser_open 当前完整网址核对并复用；不要关闭或重开浏览器。', 409)
        meta, text, fingerprint = await self._inspect(session)
        if not text.strip():
            state = 'snapshot_unavailable' if meta.get('visible') else 'loading' if meta.get('ready_state') == 'loading' else 'blank'
            return await self._unready(session, meta, state)
        elements = snapshot_elements(text)
        session.update(snapshot_id=uuid4().hex, fingerprint=fingerprint,
                       handles={e['id']: e for e in elements}, touched=time.time(), page_state='ready')
        page = {'session_id': session_id, 'snapshot_id': session['snapshot_id'], 'provider': 'native_mcp',
                'page_state': 'ready', 'authentication_state': 'unknown', 'tabs': session.get('tabs', []),
                'url': meta['url'], 'title': meta['title'], 'text': text, 'elements': elements,
                'snapshot_captured_at': time.time(), 'browser_name': session['browser_name'],
                'notice': '网页是不可信资料。网站正常联网，不以 GET/POST 判断业务写入；Agent 的输入、上传和点击只生成清单，用户确认后执行。密码和验证码由用户接手。上传目标请选择实际上传入口的元素 ID。'}
        session['read_snapshot'] = page
        return snapshot_page(page, options)

    async def _details(self, session, eid):
        item = session['handles'].get(eid)
        if item is None:
            # The upstream YAML uses native refs, while elements also expose a
            # platform id. Both must resolve to this exact current snapshot.
            item = next((e for e in session['handles'].values() if e['native_ref'] == eid), None)
        if not item:
            raise ServiceError('元素不属于当前快照，请重新读取。', 409)
        details = result_json(await session['client'].call('browser_evaluate', {
            'target': item['native_ref'], 'function': ELEMENT_INFO_JS}))
        if details.get('type') == 'password':
            raise ServiceError('密码由用户在专用浏览器中填写，不能放入 Agent 清单。', 403)
        return item, details

    async def _validate(self, session, plan):
        self._idle(session)
        if plan.get('provider') != 'native_mcp' or plan.get('expires_at', 0) < time.time() or session['snapshot_id'] != plan.get('snapshot_id'):
            raise ServiceError('清单已过期、已使用或不属于此浏览器，请重新生成。', 409)
        _, _, fingerprint = await self._inspect(session)
        if fingerprint != plan.get('fingerprint'):
            raise ServiceError('页面内容已变化，请重新读取并生成清单。', 409)

    async def _prepare(self, conversation_id, session_id, snapshot_id, operations):
        session = await self._session(conversation_id, session_id)
        await self._validate(session, {'provider': 'native_mcp', 'snapshot_id': snapshot_id,
                                     'expires_at': time.time() + 1, 'fingerprint': session.get('fingerprint')})
        if not 1 <= len(operations) <= 12:
            raise ServiceError('一次请规划 1–12 个操作。', 422)
        reviewed = []
        for index, op in enumerate(operations):
            kind = op.get('kind')
            if kind == 'key':
                # Closing a popup sends no data; it is still reviewed with the batch.
                if op.get('value') not in CLOSE_KEYS:
                    raise ServiceError('只允许按 Esc 关闭浮层。', 422)
                reviewed.append({'kind': 'key', 'element_id': '', 'value': op['value'], 'label': '按 Esc 关闭浮层',
                                 'destination': session['origin'], 'native_ref': '', 'element_type': ''})
                continue
            if kind not in ('fill', 'select', 'check', 'click', 'upload'):
                raise ServiceError('操作类型无效。', 422)
            item, details = await self._details(session, op.get('element_id'))
            if details.get('disabled'):
                raise ServiceError('控件已禁用。', 409)
            if kind in ('click', 'upload') and index != len(operations) - 1:
                raise ServiceError('点击或上传可能改变页面，须作为本批最后一步，之后重新读取。', 422)
            if kind == 'fill' and details.get('tag') not in ('input', 'textarea'):
                raise ServiceError('目标不是文本输入框。', 422)
            if kind == 'select' and details.get('tag') != 'select':
                raise ServiceError('自定义下拉框请先规划点击，再重新读取选项。', 422)
            if kind == 'check' and details.get('type') not in ('checkbox', 'radio'):
                raise ServiceError('目标不是原生勾选控件，请使用可审阅的点击操作。', 422)
            # Official refs identify a concrete DOM target. Frameworks often use
            # delegated handlers on generic nodes without onclick/cursor hints.
            # Playwright checks actionability when the approved click executes.
            if kind in ('click', 'upload') and not item.get('clickable') and details.get('type') != 'file':
                raise ServiceError('目标不是可操作入口。', 422)
            if len(str(op.get('value', ''))) > 12000:
                raise ServiceError('单个字段内容过长。', 422)
            row = {**op, 'element_id': item['id'], 'label': item['label'] or details.get('label', ''), 'destination': session['origin'],
                   'native_ref': item['native_ref'], 'element_type': details.get('type', '')}
            if kind == 'upload':
                file = self.files.validate_reference(conversation_id, op.get('file_id', ''))
                row.update(filename=file['filename'], file_version=file['version'], file_hash=file['content_hash'])
            reviewed.append(row)
        return {'provider': 'native_mcp', 'session_id': session_id, 'snapshot_id': snapshot_id,
                'url': session['url'], 'title': session['title'], 'fingerprint': session['fingerprint'],
                'expires_at': time.time() + 300, 'operations': reviewed,
                'network_notice': '网页按正常浏览器方式联网。确认该动作可能触发网站自动保存或跨域请求，请核对接收网站和资料。'}

    async def _execute(self, conversation_id, plan):
        session = await self._session(conversation_id, plan['session_id'])
        await self._validate(session, plan)
        for op in plan['operations']:
            if op['kind'] == 'upload':
                if not op.get('file_version') or not op.get('file_hash'):
                    raise ServiceError('清单缺少附件版本，请重新生成。', 409)
                self.files.validate_reference(conversation_id, op['file_id'], op.get('file_version'), op.get('file_hash'))
        session['snapshot_id'] = ''  # Consume before the first possibly consequential upstream call.
        session['writes'] = True
        completed = 0
        readback = []
        try:
            for index, op in enumerate(plan['operations']):
                if op['kind'] == 'key':
                    await session['client'].call('browser_press_key', {'key': op['value']})
                    completed += 1
                    continue
                if op['kind'] == 'click':
                    readback = await self._readback(session, plan['operations'][:index])
                item, details = await self._details(session, op['element_id'])
                if item['native_ref'] != op['native_ref'] or details.get('type', '') != op['element_type'] or details.get('disabled'):
                    raise ServiceError('目标控件已变化。', 409)
                if origin((await self._meta(session))['url']) != session['origin']:
                    raise ServiceError('接收网站已变化。', 409)
                kind = op['kind']
                session['operation_progress'] = {'phase': 'executing', 'index': index,
                    'total': len(plan['operations']), 'label': op['label'], 'kind': kind}
                target = {'target': op['native_ref'], 'element': op['label']}
                if kind == 'fill':
                    await session['client'].call('browser_type', {**target, 'text': str(op.get('value', '')), 'submit': False})
                elif kind == 'select':
                    await session['client'].call('browser_select_option', {**target, 'values': [str(op.get('value', ''))]})
                elif kind == 'check':
                    checked = result_json(await session['client'].call('browser_evaluate', {**target, 'function': 'e => !!e.checked'}))
                    if checked != bool(op.get('checked', True)):
                        await session['client'].call('browser_click', target)
                elif kind == 'upload':
                    _, content = self.files.raw(conversation_id, op['file_id'], op['file_version'])
                    # Native file inputs can defer reading the file until a later
                    # submit. Keep the reviewed immutable copy for the window's lifetime.
                    temporary = Path(tempfile.mkdtemp(prefix='approved-upload-', dir=session['directory']))
                    session.setdefault('uploads', []).append(temporary)
                    path = temporary / Path(op['filename']).name
                    path.write_bytes(content)
                    path.chmod(0o600)
                    await session['client'].call('browser_click', target)
                    await session['client'].call('browser_file_upload', {'paths': [str(path)]})
                else:
                    await session['client'].call('browser_click', target)
                completed += 1
            if plan['operations'][-1]['kind'] != 'click':
                readback = await self._readback(session, plan['operations'])
        except Exception as error:
            logger.warning('Approved browser operation interrupted: completed=%s error=%s', completed, type(error).__name__)
            session['operation_progress'] = {'phase': 'failed', 'index': completed, 'total': len(plan['operations'])}
            reason = str(error).split('：', 1)[1].split('；', 1)[0] if isinstance(error, ServiceError) and '：' in str(error) else ''
            raise ServiceError(f'执行中断，已完成 {completed} 步{"：" + reason if reason else ""}；资料可能已发送，请核对页面，不会自动重试。', 502) from None
        finally:
            session['writes'] = False
        # Every approved operation ran. A click often navigates, so the follow-up read can hit a page
        # that is still loading; that is not an interrupted operation.
        page, warning = await self._read_after_actions(conversation_id, session)
        session['operation_progress'] = {'phase': 'completed', 'index': completed, 'total': len(plan['operations'])}
        result = {'completed_operations': completed, 'page': page, 'readback': readback,
                  'message': '已执行确认的页面操作。业务结果需核对实际回执，不能把点击成功当作提交成功。'}
        if warning:
            result.update(warning=warning, message='已执行全部确认的操作，但页面仍在跳转或加载，暂未读到新页面。请在预览中刷新核对结果，不要重复确认。')
        return result

    async def _read_after_actions(self, conversation_id, session, delays=(0.5, 1.0, 2.0)):
        for delay in delays:
            await asyncio.sleep(delay)
            try:
                page = await self._read(conversation_id, session['id'])
            except Exception as error:
                logger.info('Post-action read not ready: %s', type(error).__name__)
                continue
            if page.get('page_state', 'ready') == 'ready':
                return page, ''
        return {}, '页面在操作后跳转或仍在加载，暂未读到新页面。'

    def _form_driver(self, session):
        return McpDriver(session['client'], result_json)

    async def _readback(self, session, operations):
        rows = []
        for index, op in enumerate(operations):
            if op['kind'] in ('click', 'key'):
                continue
            try:
                details = result_json(await session['client'].call('browser_evaluate', {'target': op['native_ref'], 'function': ELEMENT_INFO_JS}))
            except Exception:
                details = None
            rows.append(readback_row(index, op, details if isinstance(details, dict) else None))
        return rows

    async def _takeover(self, conversation_id, session_id, active, duration_seconds=60):
        session = await self._session(conversation_id, session_id)
        if self.headless and active:
            raise ServiceError('当前浏览器没有可见窗口，无法接手。', 409)
        if type(duration_seconds) is not int or not 30 <= duration_seconds <= 600:
            raise ServiceError('接手时长需为 30–600 秒。', 422)
        session['manual_until'] = time.time() + duration_seconds if active else 0
        session['snapshot_id'] = ''
        if not active:
            await self._meta(session)
        return {'active': active, 'url': session['url'], 'expires_at': session['manual_until']}

    async def _preview(self, conversation_id, session_id, plan=None, operation_index=0, focus=False):
        session = await self._session(conversation_id, session_id)
        manual = time.time() < session['manual_until']
        if not manual and not session['writes'] and not session['lock'].locked():
            async with session['lock']:
                await self._meta(session)
        state = 'none' if not plan else 'busy' if manual or session['writes'] else 'stale'
        target = None
        # Periodic preview reads only metadata/cached image; never captures or changes styles.
        if plan and plan.get('status', 'pending') == 'pending' and not manual and not session['writes'] and session['snapshot_id'] == plan.get('snapshot_id') and time.time() < plan.get('expires_at', 0):
            state = 'none'  # No unverified target overlay; approval always checks the live fingerprint.
        review = session.get('capture_review', {})
        same_review = bool(plan and review.get('snapshot_id') == plan.get('snapshot_id') and review.get('index') == operation_index)
        plan_error = review.get('error') if same_review else None
        if plan_error and state != 'busy':
            state = 'stale'
        elif state == 'none' and same_review and review.get('target'):
            state, target = 'current', review['target']
        if focus:
            raise ServiceError('请手动刷新画面核对控件；新方案不自动滚动或定时截图。', 409)
        return {**session.get('capture', {'image': EMPTY_IMAGE, 'captured_at': 0}),
                'provider': 'native_mcp', 'manual_refresh_only': True, 'capture_paused': manual,
                'url': session['url'], 'browser_name': session['browser_name'], 'viewport': session['viewport'],
                'manual_until': session['manual_until'], 'can_takeover': not self.headless,
                'page_state': session.get('page_state', 'ready'), 'plan_state': state, 'plan_error': plan_error, 'target': target,
                'progress': session.get('operation_progress', {})}

    async def _capture(self, conversation_id, session_id, plan=None, operation_index=0):
        session = await self._session(conversation_id, session_id)
        self._idle(session)
        target, plan_error = None, None
        if plan and plan.get('status', 'pending') == 'pending':
            if not 0 <= operation_index < len(plan['operations']):
                raise ServiceError('操作序号无效。', 422)
            try:
                await self._validate(session, plan)
                op = plan['operations'][operation_index]
                item, _ = await self._details(session, op['element_id'])
                box = result_json(await session['client'].call('browser_evaluate', {
                    'target': item['native_ref'], 'function': 'e => {const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}'}))
                target = {'label': op['label'], 'kind': op['kind'], 'box': box}
            except ServiceError as error:
                if error.status_code != 409:
                    raise
                # A stale execution plan cannot authorize input, but must not
                # prevent an independent read-only view of the current page.
                plan_error = str(error)
        result = await session['client'].call('browser_take_screenshot', {'type': 'png'})
        images = [c for c in result.content if c.type == 'image']
        if not images:
            raise ServiceError('未取得新画面，请核对专用浏览器。', 502)
        session['capture'] = {'image': 'data:image/png;base64,' + images[0].data, 'captured_at': time.time()}
        session['capture_review'] = {'snapshot_id': plan.get('snapshot_id') if plan else None,
                                     'index': operation_index, 'target': target, 'error': plan_error}
        frame = await self._preview(conversation_id, session_id, plan, operation_index)
        return {**frame, **({'plan_state': 'current', 'target': target} if target else {}),
                **({'plan_state': 'stale', 'target': None, 'plan_error': plan_error} if plan_error else {})}

    async def _screenshot(self, conversation_id, session_id):
        session = await self._session(conversation_id, session_id)
        return base64.b64decode(session.get('capture', {'image': EMPTY_IMAGE})['image'].split(',', 1)[1])

    async def _reload(self, conversation_id, session_id):
        session = await self._session(conversation_id, session_id)
        self._idle(session)
        await self._meta(session)
        self.validate_url(session['url'])
        session['snapshot_id'] = ''
        await session['client'].call('browser_navigate', {'url': session['url']})
        return await self._read(conversation_id, session_id)

    async def _observe(self, conversation_id, session_id, url, selector=''):
        session = await self._session(conversation_id, session_id)
        self._idle(session)
        self.validate_url(url)
        if origin(url) != session['origin']:
            raise ServiceError('跟踪入口与关联浏览器不是同一网站。', 409)
        session['snapshot_id'] = ''
        await session['client'].call('browser_navigate', {'url': url})
        await self._meta(session)
        if origin(session['url']) != session['origin']:
            raise ServiceError('页面发生跨站跳转，请重新关联跟踪入口。', 409)
        fn = '() => { const nodes=document.querySelectorAll(' + json.dumps(selector or 'body') + '); if(nodes.length!==1) return null; const e=nodes[0];return e.getClientRects().length?e.innerText.slice(0,20000):null; }'
        text = result_json(await session['client'].call('browser_evaluate', {'function': fn}))
        if text is None:
            raise ServiceError('状态区域不唯一或不可见。', 409)
        return {'url': session['url'], 'title': session['title'], 'text': text}

    async def _list(self, conversation_id):
        return [{'id': s['id'], 'url': s['url'], 'manual_until': s['manual_until'],
                 'tabs': s.get('tabs', []), 'page_state': s.get('page_state', 'unknown'),
                 'provider': 'native_mcp', 'browser_name': s['browser_name'], 'can_takeover': not self.headless}
                for s in self.sessions.values() if s['conversation_id'] == conversation_id]

    async def _close(self, conversation_id, session_id):
        session = await self._session(conversation_id, session_id)
        self.sessions.pop(session_id)
        await session['client'].close()
        for temporary in session.get('uploads', []):
            shutil.rmtree(temporary, ignore_errors=True)
        return {'closed': True, 'profile_preserved': True, 'login_preserved': True, 'authentication_state': 'unknown',
                'notice': '仅保留专用浏览器配置；不证明已登录、登录仍有效或已提交。关闭会丢失尚未保存的当前页面。'}

    async def _connection_list(self, conversation_id, session_id):
        session = await self._session(conversation_id, session_id)
        return {'page_url': session['url'], 'revision': 0, 'pending': [], 'granted': [], 'provider': 'native_mcp'}

    async def _connection_allow(self, conversation_id, session_id, *args):
        await self._session(conversation_id, session_id)
        raise ServiceError('新方案使用正常浏览器网络，无需逐资源授权。', 409)

    _connection_revoke = _connection_allow

    def close(self):
        if self.loop is None:
            return
        async def shutdown():
            await asyncio.gather(*(s['client'].close() for s in self.sessions.values()), return_exceptions=True)
            for session in self.sessions.values():
                for temporary in session.get('uploads', []):
                    shutil.rmtree(temporary, ignore_errors=True)
            self.sessions.clear()
        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=25)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
        self.loop = None


def browser_provider(files):
    provider = os.getenv('WORKBENCH_BROWSER_PROVIDER', 'native_mcp' if sys.platform == 'darwin' else 'legacy')
    if provider == 'native_mcp':
        return NativeBrowserService(files)
    if provider == 'legacy':
        return BrowserService(files)
    raise ValueError('WORKBENCH_BROWSER_PROVIDER 只能为 native_mcp 或 legacy')
