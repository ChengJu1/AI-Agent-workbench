"""Check the experiment's actual boundary, not website-specific markup."""
import unittest

from fastapi.testclient import TestClient
from policy import command, network_summary
from server import NONCE, create_app


class ProbeBoundaryTests(unittest.TestCase):
    def test_no_arbitrary_mcp_or_application_actions(self):
        for name in ('browser_evaluate', 'browser_run_code', 'browser_click',
                     'browser_file_upload', 'browser_type', 'submit', 'http://internal'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                command(name)
        tool, args = command('open-job')
        self.assertEqual(tool, 'browser_navigate')
        args['url'] = 'http://internal'
        self.assertNotEqual(command('open-job')[1]['url'], args['url'])

    def test_untrusted_website_cannot_control_browser(self):
        client = TestClient(create_app())
        self.assertEqual(client.post('/api/open-job').status_code, 403)
        self.assertEqual(client.post('/api/open-job', headers={
            'X-Workbench-Probe': NONCE, 'Origin': 'https://untrusted.example'}).status_code, 403)
        self.assertEqual(client.get('/', headers={'Host': 'untrusted.example'}).status_code, 400)
        self.assertEqual(client.post('/api/browser_run_code', headers={
            'X-Workbench-Probe': NONCE}).status_code, 403)

    def test_diagnostics_do_not_publish_request_data(self):
        rows = network_summary('''### Result
[POST] https://user:password@example.com/api/common/Datasource?token=secret&userId=123 => [200] OK
[GET] https://cdn.example.com/public.js?private=value => [FAILED] net::ERR_NAME_NOT_RESOLVED
Authorization: Bearer secret
{"resume":"private"}''')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {'method': 'POST', 'host': 'example.com',
                                 'path': '/api/common/Datasource', 'status': '200'})
        self.assertEqual(rows[1]['error'], 'net::ERR_NAME_NOT_RESOLVED')
        self.assertNotIn('secret', str(rows))
        self.assertNotIn('private', str(rows))


if __name__ == '__main__':
    unittest.main()
