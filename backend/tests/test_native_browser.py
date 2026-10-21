import asyncio
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

from app.errors import ServiceError
from app.platform.native_browser import NativeBrowserService, snapshot_elements, snapshot_body, tab_summaries, semantic_snapshot
from app.platform.native_mcp import NativeMcp, result_json
import test_platform_capabilities as fixtures


def text(value):
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=value)], isError=False)


class NativeBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.files = MagicMock()
        self.service = NativeBrowserService(self.files, headless=False)
        self.metadata = {'url': 'https://example.com/form', 'title': '合成表单',
                         'viewport': {'width': 1280, 'height': 720}, 'visible': True}
        self.snapshot = '- generic [ref=e1]:\n  - generic [ref=e2]: 姓名\n  - textbox "请输入" [ref=e3]\n  - button "检查" [ref=e4]'
        self.fields = {'url': self.metadata['url'], 'fields': [['name', '']]}
        self.tabs = [{'index': 0, 'current': True, 'url': self.metadata['url'], 'title': '合成表单'}]
        self.client = SimpleNamespace(call=AsyncMock(side_effect=self.call), close=AsyncMock())
        self.session = {'id': 's', 'conversation_id': 'c', 'client': self.client, 'origin': 'https://example.com',
                        'url': self.metadata['url'], 'title': '', 'viewport': self.metadata['viewport'],
                        'manual_until': 0, 'writes': False, 'snapshot_id': '', 'handles': {},
                        'lock': asyncio.Lock(), 'browser_name': 'Google Chrome'}
        self.service.sessions['s'] = self.session

    async def call(self, tool, args=None):
        import json
        from app.platform.native_browser import META_JS, FINGERPRINT_JS
        args = args or {}
        if tool == 'browser_tabs':
            if args.get('action') == 'select':
                for tab in self.tabs:
                    tab['current'] = tab['index'] == args['index']
                selected = next(t for t in self.tabs if t['current'])
                self.metadata['url'] = selected['url']
            return text('### Result\n' + '\n'.join(f"- {t['index']}:{' (current)' if t['current'] else ''} [{t['title']}]({t['url']})" for t in self.tabs))
        if tool == 'browser_evaluate':
            if args['function'] == META_JS:
                result = self.metadata
            elif args['function'] == FINGERPRINT_JS:
                result = self.fields
            else:
                result = {'tag': 'input' if args.get('target') == 'e3' or str(args.get('target')).startswith('f3e1') else 'button',
                          'type': 'text', 'label': '合成控件', 'disabled': False, 'clickable': True}
            return text('### Result\n' + json.dumps(result))
        if tool == 'browser_snapshot':
            return text('### Snapshot\n```yaml\n' + self.snapshot + '\n```')
        return text('### Result\n{}')

    async def plan(self, operations=None):
        page = await self.service._read('c', 's')
        return await self.service._prepare('c', 's', page['snapshot_id'], operations or [
            {'kind': 'fill', 'element_id': 'e_e3', 'value': '合成内容'}])

    async def test_only_approval_executes_upstream_input_and_consumes_plan(self):
        plan = await self.plan()
        self.assertFalse(any(c.args[0] == 'browser_type' for c in self.client.call.call_args_list))
        result = await self.service._execute('c', plan)
        self.assertEqual(result['completed_operations'], 1)
        calls = [c for c in self.client.call.call_args_list if c.args[0] == 'browser_type']
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].args[1]['submit'])
        with self.assertRaises(ServiceError):
            await self.service._execute('c', plan)
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_type']), 1)

    async def test_yaml_native_ref_resolves_only_in_current_snapshot(self):
        plan = await self.plan([{'kind': 'fill', 'element_id': 'e3', 'value': '合成内容'}])
        self.assertEqual(plan['operations'][0]['element_id'], 'e_e3')
        await self.service._execute('c', plan)
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_type']), 1)
        with self.assertRaises(ServiceError):
            await self.plan([{'kind': 'click', 'element_id': 'unknown', 'value': ''}])

    async def test_unnamed_upload_wrapper_uses_descendant_text_and_frame_reference(self):
        self.snapshot += '\n- generic [ref=f3e61] [cursor=pointer]:\n  - img "icon/上传" [ref=f3e64]\n  - text: 拖拽或点击上传简历，我们帮你快速解析~'
        page = await self.service._read('c', 's')
        wrapper = next(e for e in page['elements'] if e['native_ref'] == 'f3e61')
        self.assertIn('上传简历', wrapper['label'])
        self.files.validate_reference.return_value = {'filename': 'synthetic.txt', 'version': 1, 'content_hash': 'hash'}
        plan = await self.service._prepare('c', 's', page['snapshot_id'], [{'kind': 'upload', 'element_id': wrapper['id'], 'file_id': 'file'}])
        self.assertEqual(plan['operations'][0]['native_ref'], 'f3e61')
        self.assertFalse(any(c.args[0] in ('browser_click', 'browser_file_upload') for c in self.client.call.call_args_list))

    async def test_large_snapshot_paging_and_search_keep_one_complete_current_reference_map(self):
        self.snapshot += '\n' + '\n'.join(f'- textbox "长字段{i}" [ref=f3e{i+1000}]' for i in range(900))
        self.snapshot += '\n- generic [ref=f3e9999] [cursor=pointer]:\n  - text: 点击上传合成简历'
        page = await self.service._read('c', 's')
        self.assertGreater(page['page_text_total'], 25000)
        self.assertGreater(page['page_element_total'], 250)
        self.assertIsNotNone(page['next_text_offset'])
        self.assertIsNotNone(page['next_element_offset'])
        self.client.call.reset_mock()
        found = await self.service._read('c', 's', None, {'snapshot_id': page['snapshot_id'], 'query': '上传合成简历'})
        self.assertEqual(found['snapshot_id'], page['snapshot_id'])
        self.assertEqual(found['elements'][0]['native_ref'], 'f3e9999')
        self.client.call.assert_not_awaited()
        tail = await self.service._read('c', 's', None, {'snapshot_id': page['snapshot_id'], 'element_offset': 850, 'text_offset': 25000})
        self.assertIn('长字段', tail['text'])
        self.assertTrue(tail['elements'])
        await self.service._prepare('c', 's', page['snapshot_id'], [{'kind': 'fill', 'element_id': 'f3e1899', 'value': 'synthetic'}])
        refreshed = await self.service._read('c', 's')
        with self.assertRaises(ServiceError):
            await self.service._read('c', 's', None, {'snapshot_id': page['snapshot_id'], 'query': '上传'})
        with self.assertRaises(ServiceError):
            await self.service._read('other', 's', None, {'snapshot_id': refreshed['snapshot_id']})

    async def test_blank_selected_tab_recovers_unique_original_site_without_navigation(self):
        self.metadata['url'] = 'about:blank'
        self.tabs = [{'index': 0, 'current': True, 'url': 'about:blank', 'title': ''},
                     {'index': 1, 'current': False, 'url': 'https://example.com/form', 'title': '填写页'}]
        page = await self.service._read('c', 's')
        self.assertEqual(page['url'], 'https://example.com/form')
        self.assertTrue(page['elements'])
        self.assertFalse(any(c.args[0] == 'browser_navigate' for c in self.client.call.call_args_list))
        self.client.close.assert_not_awaited()

    async def test_reopen_does_not_discard_current_form(self):
        self.session['url'] = 'https://example.com/form'
        self.service.validate_url = lambda _: None
        page = await self.service._open('c', 'https://example.com/job')
        self.assertEqual(page['url'], 'https://example.com/form')
        self.assertIn('warning', page)
        self.client.close.assert_not_awaited()
        self.assertFalse(any(c.args[0] == 'browser_navigate' for c in self.client.call.call_args_list))

    async def test_blank_is_reported_as_unknown_state_not_successful_login(self):
        self.snapshot = ''
        self.metadata.update(visible=False, ready_state='complete')
        page = await self.service._read('c', 's')
        self.assertEqual(page['page_state'], 'blank')
        self.assertEqual(page['authentication_state'], 'unknown')
        self.assertFalse(page['snapshot_id'])

    async def test_multiple_candidate_tabs_require_explicit_choice(self):
        self.metadata['url'] = 'about:blank'
        self.tabs = [{'index': 0, 'current': True, 'url': 'about:blank', 'title': ''},
                     {'index': 1, 'current': False, 'url': 'https://example.com/one', 'title': '一'},
                     {'index': 2, 'current': False, 'url': 'https://example.com/two', 'title': '二'}]
        page = await self.service._read('c', 's')
        self.assertEqual(page['page_state'], 'choose_tab')
        self.assertFalse(any(c.args[0] == 'browser_tabs' and c.args[1]['action'] == 'select' for c in self.client.call.call_args_list))
        chosen = await self.service._read('c', 's', 2)
        self.assertEqual(chosen['url'], 'https://example.com/two')
        with self.assertRaises(ServiceError):
            await self.service._read('other', 's', 1)
        with self.assertRaises(ServiceError):
            await self.service._read('c', 's', 99)

    def test_missing_snapshot_is_not_silently_converted_to_empty_dom(self):
        with self.assertRaises(ServiceError):
            snapshot_body('### Result\nSnapshot saved elsewhere')
        self.assertEqual(snapshot_body('### Snapshot\n```yaml\n\n```'), '')
        tabs = tab_summaries([{'index': 1, 'current': True, 'url': 'https://example.com/form?token=secret#private', 'title': '表单'}])
        self.assertEqual(tabs[0]['url'], 'https://example.com/form')

    def test_quoted_names_keep_metadata_like_text_and_meaningful_state(self):
        node = '- button "确认 [active] [ref=e1]" [active] [ref=e2] [disabled]'
        self.assertEqual(semantic_snapshot(node), '- button "确认 [active] [ref=e1]" [disabled]')

    async def test_empty_page_diagnostics_do_not_expose_request_queries(self):
        self.snapshot = ''
        self.metadata.update(visible=False, ready_state='complete')
        original = self.call
        async def network(tool, args=None):
            if tool == 'browser_network_requests':
                return text('### Result\n[GET] https://cdn.example/secret-path?token=private => [FAILED] net::ERR_NAME_NOT_RESOLVED')
            return await original(tool, args)
        self.client.call.side_effect = network
        page = await self.service._read('c', 's')
        self.assertEqual(page['diagnostics']['failed_resources'], [
            {'host': 'cdn.example', 'status': 'FAILED', 'error': 'net::ERR_NAME_NOT_RESOLVED'}])
        self.assertNotIn('private', str(page))
        self.assertNotIn('secret-path', str(page))

    async def test_framework_generic_target_can_be_approved_without_cursor_heuristics(self):
        self.snapshot += '\n- generic [ref=apply]: 立即办理'
        original = self.call
        async def framework(tool, args=None):
            if tool == 'browser_evaluate' and (args or {}).get('target') == 'apply':
                return text('### Result\n{"tag":"div","type":"","disabled":false,"clickable":false}')
            return await original(tool, args)
        self.client.call.side_effect = framework
        plan = await self.plan([{'kind': 'click', 'element_id': 'e_apply'}])
        self.assertFalse(any(c.args[0] == 'browser_click' for c in self.client.call.call_args_list))
        await self.service._execute('c', plan)
        clicks = [c for c in self.client.call.call_args_list if c.args[0] == 'browser_click']
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0].args[1]['target'], 'apply')

    async def test_navigation_after_approved_click_is_not_reported_as_interrupted(self):
        self.snapshot += '\n- button "立即投递" [ref=e9]'
        original, state = self.call, {'clicked': False, 'failed_reads': 0}
        async def navigating(tool, args=None):
            if tool == 'browser_click':
                state['clicked'] = True
                self.metadata['url'] = 'https://example.com/form?step=2'
                self.fields['url'] = self.metadata['url']
            if state['clicked'] and tool == 'browser_evaluate' and (args or {}).get('function') == META_JS and state['failed_reads'] < 2:
                state['failed_reads'] += 1
                raise ServiceError('Execution context was destroyed', 502)
            return await original(tool, args)
        from app.platform.native_browser import META_JS
        self.client.call.side_effect = navigating
        plan = await self.plan([{'kind': 'click', 'element_id': 'e_e9'}])
        with patch('app.platform.native_browser.asyncio.sleep', AsyncMock()):
            result = await self.service._execute('c', plan)
        self.assertEqual(result['completed_operations'], 1)
        self.assertEqual(result['page']['url'], 'https://example.com/form?step=2')
        self.assertNotIn('warning', result)
        # Still unreadable after retries: completed, with a warning instead of a failure.
        state.update(clicked=False, failed_reads=-10)
        plan = await self.plan([{'kind': 'click', 'element_id': 'e_e9'}])
        with patch('app.platform.native_browser.asyncio.sleep', AsyncMock()):
            result = await self.service._execute('c', plan)
        self.assertEqual(result['completed_operations'], 1)
        self.assertEqual(result['page'], {})
        self.assertIn('warning', result)
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_click']), 2)

    async def test_escape_closes_popup_in_same_batch_and_blocked_click_explains_why(self):
        from app.platform.browser import browser_error_reason
        self.assertIn('遮挡', browser_error_reason('Timeout 5000ms exceeded. <div class="el-cascader__dropdown"> intercepts pointer events'))
        self.assertEqual(browser_error_reason('unrelated'), '')
        with self.assertRaises(ServiceError):
            await self.plan([{'kind': 'key', 'value': 'Enter'}, {'kind': 'click', 'element_id': 'e_e4'}])
        plan = await self.plan([{'kind': 'key', 'value': 'Escape'}, {'kind': 'click', 'element_id': 'e_e4'}])
        self.assertEqual(plan['operations'][0]['label'], '按 Esc 关闭浮层')
        original = self.call
        async def blocked(tool, args=None):
            if tool == 'browser_click':
                raise ServiceError('浏览器工具未完成：' + browser_error_reason('<div> intercepts pointer events') + '；页面可能已变化，请核对实际页面，不会自动重试。', 409)
            return await original(tool, args)
        self.client.call.side_effect = blocked
        with self.assertRaises(ServiceError) as interrupted:
            await self.service._execute('c', plan)
        self.assertIn('已完成 1 步：目标被其他元素遮挡', str(interrupted.exception))
        keys = [c for c in self.client.call.call_args_list if c.args[0] == 'browser_press_key']
        self.assertEqual(keys[0].args[1], {'key': 'Escape'})

    async def test_changed_page_and_other_conversation_cannot_execute(self):
        plan = await self.plan()
        self.fields['fields'][0][1] = '用户手动更改'
        with self.assertRaises(ServiceError):
            await self.service._execute('c', plan)
        with self.assertRaises(ServiceError):
            await self.service._read('other', 's')
        self.assertFalse(any(c.args[0] == 'browser_type' for c in self.client.call.call_args_list))

    async def test_focus_and_snapshot_reference_annotations_do_not_invalidate_reviewed_content(self):
        plan = await self.plan()
        self.snapshot = self.snapshot.replace('[ref=e1]', '[ref=e91]').replace('[ref=e3]', '[active] [ref=e3]')
        await self.service._execute('c', plan)
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_type']), 1)

    async def test_text_that_looks_like_snapshot_metadata_is_still_reviewed_content(self):
        self.snapshot += '\n- text: 声明 [ref=e12] [active]'
        plan = await self.plan()
        self.snapshot = self.snapshot.replace('声明 [ref=e12]', '声明 [ref=e13]')
        with self.assertRaises(ServiceError):
            await self.service._execute('c', plan)
        self.assertFalse(any(c.args[0] == 'browser_type' for c in self.client.call.call_args_list))

    async def test_stale_plan_does_not_prevent_current_read_only_screenshot(self):
        plan = await self.plan()
        self.fields['fields'][0][1] = '用户修改了字段'
        original = self.call
        async def screenshot(tool, args=None):
            if tool == 'browser_take_screenshot':
                return SimpleNamespace(content=[SimpleNamespace(type='image', data='c3ludGhldGlj')])
            return await original(tool, args)
        self.client.call.side_effect = screenshot
        frame = await self.service._capture('c', 's', plan)
        self.assertGreater(frame['captured_at'], 0)
        self.assertEqual(frame['plan_state'], 'stale')
        self.assertIsNone(frame['target'])
        self.assertIn('变化', frame['plan_error'])
        cached = await self.service._preview('c', 's', plan)
        self.assertEqual(cached['captured_at'], frame['captured_at'])
        self.assertEqual(cached['plan_state'], 'stale')
        self.assertIn('变化', cached['plan_error'])
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_take_screenshot']), 1)
        self.assertEqual(self.session['snapshot_id'], plan['snapshot_id'])
        with self.assertRaises(ServiceError):
            await self.service._execute('c', plan)
        self.assertFalse(any(c.args[0] == 'browser_type' for c in self.client.call.call_args_list))

    async def test_file_version_checked_before_any_upload(self):
        plan = await self.plan([{'kind': 'upload', 'element_id': 'e_e4', 'file_id': 'file'}])
        self.files.validate_reference.side_effect = ServiceError('版本已改变', 409)
        self.client.call.reset_mock()
        with self.assertRaises(ServiceError):
            await self.service._execute('c', plan)
        self.assertFalse(any(c.args[0] in ('browser_click', 'browser_file_upload') for c in self.client.call.call_args_list))

    async def test_selected_file_exists_until_browser_closes_for_deferred_form_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            self.session['directory'] = Path(directory)
            self.files.validate_reference.return_value = {'filename': 'synthetic.txt', 'version': 1, 'content_hash': 'hash'}
            self.files.raw.return_value = ({}, b'synthetic file')
            plan = await self.plan([{'kind': 'upload', 'element_id': 'e_e4', 'file_id': 'file'}])
            await self.service._execute('c', plan)
            uploaded = next(c.args[1]['paths'][0] for c in self.client.call.call_args_list if c.args[0] == 'browser_file_upload')
            self.assertEqual(Path(uploaded).read_bytes(), b'synthetic file')
            await self.service._close('c', 's')
            self.assertFalse(Path(uploaded).exists())

    async def test_manual_pause_blocks_dom_capture_and_invalidates_approval(self):
        plan = await self.plan()
        await self.service._takeover('c', 's', True, 300)
        self.client.call.reset_mock()
        frame = await self.service._preview('c', 's', plan)
        self.assertTrue(frame['capture_paused'])
        for method, args in [(self.service._read, ('c', 's')), (self.service._capture, ('c', 's')),
                             (self.service._execute, ('c', plan))]:
            with self.assertRaises(ServiceError):
                await method(*args)
        self.client.call.assert_not_awaited()

    async def test_periodic_preview_and_screenshot_never_capture(self):
        await self.service._preview('c', 's')
        await self.service._screenshot('c', 's')
        self.assertFalse(any(c.args[0] == 'browser_take_screenshot' for c in self.client.call.call_args_list))
        self.assertTrue((await self.service._preview('c', 's'))['manual_refresh_only'])

    async def test_handback_requires_fresh_plan_and_does_not_execute_old_batch(self):
        old = await self.plan()
        await self.service._takeover('c', 's', True, 300)
        await self.service._takeover('c', 's', False)
        with self.assertRaises(ServiceError):
            await self.service._execute('c', old)
        new = await self.plan()
        self.assertNotEqual(old['snapshot_id'], new['snapshot_id'])
        self.assertFalse(any(c.args[0] == 'browser_type' for c in self.client.call.call_args_list))
        await self.service._execute('c', new)
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_type']), 1)

    async def test_closed_window_drops_session_without_automatically_reopening(self):
        self.client.call.side_effect = ServiceError('窗口已关闭', 410)
        with self.assertRaises(ServiceError):
            await self.service._dispatch('preview', 'c', 's')
        self.assertNotIn('s', self.service.sessions)
        self.client.close.assert_awaited_once()
        self.assertFalse(any(c.args[0] == 'browser_navigate' for c in self.client.call.call_args_list))

    async def test_timeout_does_not_retry_input_or_preserve_old_plan(self):
        plan = await self.plan()
        async def failing(tool, args=None):
            if tool == 'browser_type':
                raise TimeoutError()
            return await self.call(tool, args)
        self.client.call.side_effect = failing
        self.client.call.reset_mock()
        with self.assertRaises(ServiceError):
            await self.service._execute('c', plan)
        self.assertEqual(len([c for c in self.client.call.call_args_list if c.args[0] == 'browser_type']), 1)
        self.assertEqual(self.session['snapshot_id'], '')
        self.assertEqual(self.session['operation_progress']['phase'], 'failed')

    async def test_cross_site_navigation_and_password_are_rejected(self):
        self.metadata['url'] = 'https://other.example/form'
        with self.assertRaises(ServiceError):
            await self.service._read('c', 's')
        self.metadata['url'] = 'https://example.com/form'
        original = self.call
        async def password(tool, args=None):
            if tool == 'browser_evaluate' and (args or {}).get('target'):
                return text('### Result\n{"tag":"input","type":"password"}')
            return await original(tool, args)
        self.client.call.side_effect = password
        with self.assertRaises(ServiceError):
            await self.plan()

    async def test_hidden_upstream_code_tools_cannot_be_called(self):
        client = NativeMcp.__new__(NativeMcp)
        client.ready = asyncio.get_running_loop().create_future()
        client.ready.set_result(True)
        client.task = MagicMock(done=lambda: False)
        for name in ('browser_run_code', 'browser_run_code_unsafe', 'browser_storage_state', 'browser_drop'):
            with self.assertRaises(ServiceError):
                await client.call(name, {'code': 'arbitrary'})

    def test_official_refs_and_surrounding_labels_are_preserved(self):
        elements = snapshot_elements(self.snapshot)
        self.assertEqual(next(e for e in elements if e['native_ref'] == 'e3')['label'], '姓名')
        self.assertEqual(result_json(text('### Result\n{"ok":true}\n### Page\n...')), {'ok': True})
        long_form = '\n'.join(f'- generic [ref=x{i}]: 标签{i}' for i in range(260)) + '\n- button "最后的提交按钮" [ref=last]'
        self.assertEqual(snapshot_elements(long_form)[0]['native_ref'], 'last')


class NativeCaptureApiTests(unittest.TestCase):
    setUp = fixtures.PlatformCapabilitiesTest.setUp

    def test_read_tool_exposes_validated_paging_and_forwards_snapshot_options(self):
        from app.tools.platform_tools import BrowserRead
        sid = 'browser_' + '1'*32
        args = BrowserRead.model_validate({'session_id': sid, 'snapshot_id': 'snapshot', 'query': '上传', 'element_offset': 80}).model_dump()
        self.fake.status = lambda: {'provider': 'native_mcp'}
        self.fake.call = MagicMock(return_value={'snapshot_id': 'snapshot', 'elements': []})
        self.services.platform.execute(self.cid, 'browser_read', args)
        self.assertEqual(self.fake.call.call_args.args, ('read', self.cid, sid, None, {'snapshot_id': 'snapshot', 'query': '上传', 'element_offset': 80}))
        with self.assertRaises(ServiceError):
            self.services.platform.execute(self.cid, 'browser_read', {'session_id': sid, 'element_offset': 80})
        for bad in ({'text_offset': -1}, {'element_limit': 50000}, {'query': 'x'*101}):
            with self.assertRaises(ValueError):
                BrowserRead.model_validate({'session_id': sid, **bad})
        self.services.registry.bind_platform(self.agent.id, [])
        self.fake.call.reset_mock()
        with self.assertRaises(ServiceError):
            self.services.platform.execute(self.cid, 'browser_read', args)
        self.fake.call.assert_not_called()

    def test_capture_checks_capability_and_plan_ownership_before_calling_browser(self):
        self.fake.status = lambda: {'provider': 'native_mcp'}
        self.fake.call = MagicMock(return_value={'image': 'synthetic'})
        path = f'/api/conversations/{self.cid}/browser/browser_{"1"*32}/preview-capture'
        other = self.services.store.create(self.agent.id)
        foreign = self.services.tool_store.create_pending_action(other, self.agent.id, 'workbench_platform',
            'browser_actions', {'session_id': 'browser_' + '1'*32})
        self.assertEqual(self.client.post(path, json={'action_id': foreign}).status_code, 404)
        self.fake.call.assert_not_called()
        self.assertEqual(self.client.post(path, json={}).status_code, 200)
        self.assertEqual(self.fake.call.call_args.args[0], 'capture')
        self.services.registry.bind_platform(self.agent.id, [])
        self.fake.call.reset_mock()
        self.assertEqual(self.client.post(path, json={}).status_code, 403)
        self.fake.call.assert_not_called()

    def test_runtime_prompt_uses_provider_rules_instead_of_old_network_workarounds(self):
        from app.services.claude_runtime import ClaudeRuntimeService
        runtime = ClaudeRuntimeService(audit_store=self.services.tool_store)
        runtime._platform_tools = SimpleNamespace(browser=SimpleNamespace(status=lambda: {'provider': 'native_mcp'}))
        agent = self.services.registry.get_agent(self.agent.id)
        prompt = runtime._build_prompt(agent, '')
        self.assertIn('当前 provider 为 native_mcp', prompt)
        self.assertNotIn('## 网页连接受限的处理', prompt)
        self.assertNotIn('到期后手动触发的 POST 会被阻止', prompt)
        self.assertIn('不能把整个任务转交给用户', prompt)
        self.assertIn('只有返回待确认 action_id', prompt)

    def test_inspect_requires_capability_and_uses_conversation_scoped_read(self):
        self.fake.status = lambda: {'provider': 'native_mcp'}
        self.fake.call = MagicMock(return_value={'url': 'https://example.com/form', 'page_state': 'ready',
                                                'text': 'synthetic', 'elements': [{'id': 'one'}]})
        path = f'/api/conversations/{self.cid}/browser/browser_{"1"*32}/inspect'
        response = self.client.post(path, json={'tab_index': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['element_count'], 1)
        self.assertNotIn('text', response.json())
        self.assertEqual(self.fake.call.call_args.args, ('read', self.cid, 'browser_'+'1'*32, 2))
        self.fake.call.return_value.update(page_element_total=901, page_text_total=141421)
        summary = self.client.post(path, json={}).json()
        self.assertEqual(summary['element_count'], 901)
        self.assertEqual(summary['text_length'], 141421)
        self.assertEqual(self.client.post(path, json={'tab_index': -1}).status_code, 422)
        self.services.registry.bind_platform(self.agent.id, [])
        self.fake.call.reset_mock()
        self.assertEqual(self.client.post(path, json={}).status_code, 403)
        self.fake.call.assert_not_called()
