"""Read-only project code: bindings, path safety, secret hiding, limits and the tool flow."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.platform import code
from app.runtime.prompts import build_system_prompt
from scripted_turn import ScriptedTurn


def write(root, relative, content):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)
    return path


class CodeProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'synthetic-project'
        write(self.root, 'app/main.py', 'import os\n\n\nclass Service:\n    def run(self):\n        return 1\n\n\ndef helper():\n    API_KEY = "sk-abcdefghijklmnopqrstuvwx"\n    return "ok"\n')
        write(self.root, 'web/App.tsx', 'export function App() {\n  return null\n}\nexport const useThing = () => 1\ninterface Props {}\n')
        write(self.root, '.env', 'SECRET=real-value\n')
        write(self.root, '.env.example', 'SECRET=\n')
        write(self.root, 'keys/server.pem', '-----BEGIN PRIVATE KEY-----\n')
        write(self.root, 'node_modules/lib/index.js', 'needle\n')
        write(self.root, 'logo.bin', b'\x89PNG\0\0data')
        write(self.root, 'big.txt', 'x' * (code.MAX_FILE_BYTES + 1))
        write(self.root, 'long.py', ''.join(f'line_{index} = {index}\n' for index in range(1, 1001)))
        write(self.base, 'outside.txt', 'needle outside\n')
        os.symlink(self.base / 'outside.txt', self.root / 'escape.txt')
        self.services = build_services(Settings(database_path=self.base / 'synthetic.db'))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        created = self.client.post('/api/agents', json={'name': '合成代码助手', 'description': '合成', 'system_prompt': '读代码回答',
                                                      'platform_capabilities': ['code']}).json()
        self.agent_id = created['id']
        self.cid = self.services.conversations.create(self.agent_id)
        added = self.client.post(f'/api/agents/{self.agent_id}/code-projects', json={'path': str(self.root)})
        self.assertEqual(added.status_code, 201, added.text)
        self.project = added.json()['id']
        self.code = self.services.platform.code

    def run_tool(self, name, **arguments):
        return self.services.platform.execute(self.cid, name, {'project_id': self.project, **arguments})

    def test_binding_rules(self):
        url = f'/api/agents/{self.agent_id}/code-projects'
        self.assertEqual(self.client.post(url, json={'path': 'relative/path'}).status_code, 422)
        self.assertEqual(self.client.post(url, json={'path': str(self.base / 'missing')}).status_code, 404)
        self.assertEqual(self.client.post(url, json={'path': str(self.root / 'app/main.py')}).status_code, 422)
        self.assertEqual(self.client.post(url, json={'path': '/'}).status_code, 422)
        self.assertEqual(self.client.post(url, json={'path': str(Path.home())}).status_code, 422)
        self.assertEqual(self.client.post(url, json={'path': str(self.root)}).status_code, 409)
        for index in range(2):
            (self.base / f'p{index}').mkdir()
            self.assertEqual(self.client.post(url, json={'path': str(self.base / f'p{index}')}).status_code, 201)
        (self.base / 'p3').mkdir()
        self.assertEqual(self.client.post(url, json={'path': str(self.base / 'p3')}).status_code, 422)
        listed = self.client.get(url).json()['projects']
        self.assertEqual(len(listed), 3)
        self.assertEqual(self.client.delete(f'{url}/{self.project}').json(), {'removed': True})
        self.assertEqual(self.client.delete(f'{url}/{self.project}').status_code, 404)

    def test_directory_browser_lists_subfolders_for_the_picker(self):
        listed = self.client.get('/api/local-directories', params={'path': str(self.root)}).json()
        self.assertEqual((listed['path'], listed['parent']), (str(self.root), str(self.base)))
        self.assertEqual([entry['name'] for entry in listed['directories']], ['app', 'keys', 'web'])
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        parent = self.client.get('/api/local-directories', params={'path': str(self.base)}).json()
        self.assertEqual([(entry['name'], entry['git']) for entry in parent['directories']], [('synthetic-project', True)])
        self.assertEqual(self.client.get('/api/local-directories').json()['path'], str(Path.home().resolve()))
        self.assertEqual(self.client.get('/api/local-directories', params={'path': str(self.base / 'missing')}).status_code, 404)
        self.assertEqual(self.client.get('/api/local-directories', params={'path': str(self.root / 'app/main.py')}).status_code, 422)

    def test_projects_are_scoped_to_the_agent(self):
        other = self.client.post('/api/agents', json={'name': '另一个', 'description': '合成', 'system_prompt': '合成',
                                                    'platform_capabilities': ['code']}).json()
        other_cid = self.services.conversations.create(other['id'])
        self.assertEqual(self.services.platform.execute(other_cid, 'code_projects', {}), {'projects': []})
        with self.assertRaises(ServiceError) as caught:
            self.services.platform.execute(other_cid, 'code_read', {'project_id': self.project, 'path': 'app/main.py', 'start_line': 1, 'end_line': None})
        self.assertEqual(caught.exception.status_code, 404)

    def test_paths_cannot_leave_the_project_or_reach_secrets(self):
        for path, status in [('../outside.txt', 422), ('/etc/passwd', 422), ('~/x', 422), ('escape.txt', 403),
                             ('.env', 403), ('keys/server.pem', 403), ('node_modules/lib/index.js', 403)]:
            with self.subTest(path=path), self.assertRaises(ServiceError) as caught:
                self.run_tool('code_read', path=path, start_line=1, end_line=None)
            self.assertEqual(caught.exception.status_code, status)
        self.assertIn('SECRET=', self.run_tool('code_read', path='.env.example', start_line=1, end_line=None)['content'])

    def test_listing_hides_secrets_and_dependencies(self):
        paths = {entry['path'] for entry in self.run_tool('code_list', path='', depth=3)['entries']}
        self.assertTrue({'app', 'app/main.py', 'web/App.tsx', '.env.example'} <= paths)
        self.assertFalse({'.env', 'keys/server.pem', 'node_modules', 'node_modules/lib/index.js'} & paths)
        top = self.run_tool('code_list', path='', depth=1)['entries']
        self.assertTrue(all('/' not in entry['path'] for entry in top))
        self.assertEqual([entry['path'] for entry in self.run_tool('code_list', path='app', depth=1)['entries']], ['app/main.py'])

    def test_gitignore_is_respected_in_repositories(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        write(self.root, '.gitignore', 'generated/\n')
        write(self.root, 'generated/out.py', 'needle\n')
        paths = {entry['path'] for entry in self.run_tool('code_list', path='', depth=3)['entries']}
        self.assertIn('app/main.py', paths)
        self.assertNotIn('generated/out.py', paths)
        self.assertEqual(self.run_tool('code_search', pattern='needle', regex=False, case_sensitive=False, glob=None, path='')['matches'], [])

    def test_reading_is_numbered_bounded_and_masks_secrets(self):
        first = self.run_tool('code_read', path='long.py', start_line=1, end_line=None)
        self.assertEqual((first['end_line'], first['total_lines'], first['next_start_line']), (code.DEFAULT_READ_LINES, 1000, code.DEFAULT_READ_LINES + 1))
        self.assertTrue(first['content'].startswith('  1| line_1 = 1'))
        capped = self.run_tool('code_read', path='long.py', start_line=900, end_line=2000)
        self.assertEqual((capped['end_line'], capped['next_start_line']), (1000, None))
        wide = self.run_tool('code_read', path='long.py', start_line=1, end_line=1000)
        self.assertEqual(wide['end_line'], code.MAX_READ_LINES)
        main = self.run_tool('code_read', path='app/main.py', start_line=1, end_line=None)['content']
        self.assertNotIn('sk-abcdefghijklmnopqrstuvwx', main)
        self.assertIn('API_KEY = "***"', main)
        for path in ('logo.bin', 'big.txt'):
            with self.subTest(path=path), self.assertRaises(ServiceError):
                self.run_tool('code_read', path=path, start_line=1, end_line=None)

    def test_search_supports_literal_regex_and_filters(self):
        found = self.run_tool('code_search', pattern='def helper', regex=False, case_sensitive=False, glob=None, path='')
        self.assertEqual([(match['path'], match['line']) for match in found['matches']], [('app/main.py', 9)])
        regex = self.run_tool('code_search', pattern=r'^export (function|const) \w+', regex=True, case_sensitive=True, glob='*.tsx', path='')
        self.assertEqual([match['line'] for match in regex['matches']], [1, 4])
        self.assertEqual(self.run_tool('code_search', pattern='needle', regex=False, case_sensitive=False, glob=None, path='')['matches'], [])
        masked = self.run_tool('code_search', pattern='API_KEY', regex=False, case_sensitive=True, glob=None, path='app')
        self.assertNotIn('sk-', masked['matches'][0]['text'])
        many = self.run_tool('code_search', pattern='line_', regex=False, case_sensitive=False, glob=None, path='')
        self.assertEqual((len(many['matches']), many['truncated']), (code.MAX_SEARCH_RESULTS, True))
        with self.assertRaises(ServiceError):
            self.run_tool('code_search', pattern='(', regex=True, case_sensitive=False, glob=None, path='')
        with patch.object(code, 'SEARCH_SECONDS', -1):
            stopped = self.run_tool('code_search', pattern='x', regex=False, case_sensitive=False, glob=None, path='')
        self.assertTrue(stopped['truncated'])
        self.assertIn('notice', stopped)

    def test_outline_lists_symbols_with_lines(self):
        python = self.run_tool('code_outline', path='app/main.py')['symbols']
        self.assertEqual([(item['name'], item['kind'], item['line']) for item in python],
                         [('Service', 'class', 4), ('Service.run', 'method', 5), ('helper', 'function', 9)])
        # Masking a secret-looking literal must not break parsing: the outline reads the unmasked source.
        write(self.root, 'patterns.py', 'PATTERN = re.compile(r\'token\\s*[:=]\\s*["\\\']([^"\\\']{8,})\')\n\n\ndef check():\n    pass\n')
        self.assertEqual([item['name'] for item in self.run_tool('code_outline', path='patterns.py')['symbols']], ['check'])
        script = self.run_tool('code_outline', path='web/App.tsx')['symbols']
        self.assertEqual([(item['name'], item['kind']) for item in script], [('App', 'function'), ('useThing', 'function'), ('Props', 'interface')])

    def test_tools_and_guidance_need_the_capability(self):
        agent = self.services.registry.get_agent(self.agent_id)
        self.assertIn('code_search', build_system_prompt(agent, None, 1000))
        self.client.put(f'/api/agents/{self.agent_id}/capabilities', json={'capabilities': ['files']})
        agent = self.services.registry.get_agent(self.agent_id)
        self.assertNotIn('code_search', build_system_prompt(agent, None, 1000))
        with self.assertRaises(ServiceError) as caught:
            self.services.platform.execute(self.cid, 'code_projects', {})
        self.assertEqual(caught.exception.status_code, 403)

    def test_agent_searches_then_reads_and_answers_from_real_results(self):
        model = ScriptedTurn(responses=['unused'], calls=[
            ('mcp__workbench_platform__code_projects', {}),
            ('mcp__workbench_platform__code_search', {'project_id': self.project, 'pattern': 'def helper'}),
            ('mcp__workbench_platform__code_read', {'project_id': self.project, 'path': 'app/main.py', 'start_line': 9, 'end_line': 11}),
        ], reply=lambda results: f"helper 在 app/main.py:{results[1]['matches'][0]['line']}")
        self.services.deep_agents.model_factory = lambda: model
        response = self.client.post(f'/api/conversations/{self.cid}/messages/stream', json={'content': 'helper 在哪'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(model.results[0]['projects'][0]['id'], self.project)
        self.assertIn('9| def helper', model.results[2]['content'])
        self.assertNotIn('sk-abcdefghijklmnopqrstuvwx', json.dumps(model.results, ensure_ascii=False))
        self.assertIn('helper 在 app/main.py:9', response.text)


if __name__ == '__main__':
    unittest.main()
