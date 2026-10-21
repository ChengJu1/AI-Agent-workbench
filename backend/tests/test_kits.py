"""The core stays generic: a kit's tools, data, prompt and state reach only the Agents that enable it."""
import re
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.container import build_services
from app.kits.registry import MANIFESTS, kits
from app.models.agents import LoadedAgent, PermissionsManifest
from app.platform.catalog import CATALOG, TOOL_CAPABILITIES
from app.runtime.prompts import build_system_prompt
from app.runtime.task_context import TaskContextBuilder

APP = Path(__file__).resolve().parents[1] / 'app'
JOB_WORDS = re.compile(r'投递|简历|岗位|网申|招聘|秋招|职位|面试|笔试')


def agent(*capabilities):
    return LoadedAgent(id='a1', name='合成 Agent', description='d', system_prompt='通用助手。', skills=[], tools=[],
                       permissions=PermissionsManifest(dry_run_by_default=True), platform_capabilities=list(capabilities))


class KitBoundaryTests(unittest.TestCase):
    def test_core_source_carries_no_job_wording(self):
        offenders = [f'{path.relative_to(APP)}:{number}'
                     for path in APP.rglob('*') if path.suffix in ('.py', '.sql') and 'kits' not in path.parts
                     for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1) if JOB_WORDS.search(line)]
        self.assertEqual(offenders, [])

    def test_prompt_and_state_include_a_kit_only_when_the_agent_enables_it(self):
        with tempfile.TemporaryDirectory() as folder:
            services = build_services(Settings(database_path=Path(folder) / 'k.db', backup_keep=0))
            context = TaskContextBuilder(services.store.database, services.tool_store)
            generic = agent('files', 'web', 'browser', 'tracking')
            prompt = build_system_prompt(generic, '', 1000, native_browser=True)
            self.assertIsNone(JOB_WORDS.search(prompt))
            self.assertNotIn('"applications"', context.build_task_context('c1', generic))
            job = agent('files', 'browser', 'applications')
            self.assertIn('## 投递台账', build_system_prompt(job, '', 1000))
            self.assertIn('"applications": []', context.build_task_context('c1', job))

    def test_registry_matches_the_kit_implementations(self):
        self.assertEqual([m['id'] for m in MANIFESTS], [kit.ID for kit in kits()])
        for manifest, kit in zip(MANIFESTS, kits()):
            self.assertEqual(set(manifest['tools']), set(kit.DEFINITIONS))
            self.assertTrue(all(TOOL_CAPABILITIES[tool] == kit.ID for tool in manifest['tools']))
            self.assertIn(kit.ID, [entry['id'] for entry in CATALOG])
        core_schema = (APP / 'storage' / 'schema.sql').read_text(encoding='utf-8')
        self.assertNotIn('applications', core_schema)
        self.assertNotIn('profile_versions', core_schema)


if __name__ == '__main__':
    unittest.main()
