"""Disposable UI acceptance: real API/storage, synthetic plans, no external model or user DB.
Build frontend with VITE_API_BASE_URL='' npm run build -- --outDir ../backend/data/platform-validation/skill-ui-dist, then run from backend: .venv/bin/python tests/builder_skill_validation_server.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.models.builds import BuildPlan
from app.models.skills import SkillDefinition


class SyntheticGenerator:
    async def generate(self, history, previous=None, feedback=None, discovery=None):
        match = discovery.search({'query': '周报'})['matches'][0]
        discovery.read({'skill_id': match['skill_id'], 'version': match['version']})
        return BuildPlan(status='ready', message='合成页面验收：已有周报方法可复用，新增复盘草稿由你审阅保存。',
                         name='合成周报与复盘助手', description='仅用于验收 Skill 发现、编辑保存和固定版本绑定。',
                         system_prompt='按需读取绑定 Skill。',
                         reused_skills=[{'skill_id': match['skill_id'], 'version': match['version'], 'coverage': 'partial', 'reason': '覆盖周报的成果、阻碍与计划，复盘规则需要补充。'}],
                         skill_drafts=[{'name': '周度复盘', 'description': '总结本周得失并形成下一周行动。',
                                        'content': '## 适用场景\n完成周报后需要回顾工作方法。\n\n## 步骤\n1. 对照计划与实际结果。\n2. 区分事实、推测和缺失信息。\n3. 给出一项可验证的改进。', 'reason': '已有周报规则不包含复盘方法。'}])


def main():
    with tempfile.TemporaryDirectory(prefix='workbench-skill-ui-') as temporary:
        settings = Settings(database_path=Path(temporary) / 'test.db')
        services = build_services(settings)
        services.skills.save(SkillDefinition(name='周报整理', description='将记录整理为成果、阻碍与下周计划。', content='## 工作方法\n只依据用户提供的事实整理。'))
        services.agent_builds.generator = SyntheticGenerator()
        app = create_app(settings, services)
        dist = Path(__file__).resolve().parents[1] / 'data' / 'platform-validation' / 'skill-ui-dist'
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
        @app.get('/')
        def index():
            return FileResponse(dist / 'index.html')
        uvicorn.run(app, host='127.0.0.1', port=8088, log_level='warning')


if __name__ == '__main__':
    main()
