"""Generate, independently test, and publish one immutable capability package."""
import json
import logging
import time

from jsonschema import Draft202012Validator
from starlette.concurrency import run_in_threadpool

from app.capabilities.sandbox import CodeSandbox
from app.errors import ServiceError
from app.models.builds import BuildPlan
from app.services.build_generator import BuildGenerator
from app.services.build_skills import BuildSkillDiscovery
from app.storage.build_store import BuildStore, plan_hash

logger = logging.getLogger(__name__)


def same_json(actual, expected):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(same_json(actual[key], expected[key]) for key in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(same_json(left, right) for left, right in zip(actual, expected))
    return actual == expected


class AgentBuildService:
    def __init__(self, database, generator=None, sandbox=None, skill_budget_chars=80000):
        self.store = BuildStore(database)
        self.generator = generator or BuildGenerator()
        self.sandbox = sandbox or CodeSandbox()
        self.skill_budget_chars = skill_budget_chars

    def test_plan(self, plan):
        reports = [{"method": "platform", "name": "基础能力配置校验（非外部网站实测）", "passed": True, "error": None}] if plan.capabilities else []
        if plan.reused_skills:
            reports.append({'method': 'skills', 'name': 'Skill 固定版本与实际读取记录校验（非任务执行验收）', 'passed': True, 'error': None})
        if plan.skill_drafts:
            reports.append({'method': 'skills', 'name': 'Skill 草稿格式校验（待用户审阅保存）', 'passed': True, 'error': None})
        started = time.monotonic()
        for method in plan.tools:
            for test in method.tests:
                if time.monotonic() - started > 40:
                    raise ServiceError('本轮方法测试耗时过长，请减少方法数量或简化计算。', 422)
                try:
                    result = self.sandbox.execute(method.code, test.arguments)
                    Draft202012Validator(method.output_schema).validate(result)
                    # Finite JSON numbers compare by value (6 == 6.0); true is not 1.
                    json.dumps(result, allow_nan=False)
                    passed = same_json(result, test.expected)
                    report = {'method': method.name, 'name': test.name, 'passed': passed,
                              'error': None if passed else '实际结果与预期不一致。', 'actual': result, 'expected': test.expected}
                except ServiceError as error:
                    if error.status_code == 503:
                        raise
                    report = {'method': method.name, 'name': test.name, 'passed': False, 'error': str(error)}
                except Exception:
                    report = {'method': method.name, 'name': test.name, 'passed': False, 'error': '返回结果不符合输出 Schema。'}
                reports.append(report)
        return reports

    async def process(self, build_id, revision):
        build = self.store.get(build_id)
        if build['revision'] != revision or build['status'] != 'generating':
            return
        previous, feedback = build['plan'], None
        discovery = BuildSkillDiscovery(self.store.database, self.skill_budget_chars)
        try:
            discovery.initial(previous)
            # The model can repair once using actual test failures; it cannot mark tests passed.
            for attempt in range(2):
                try:
                    plan = await self.generator.generate(build['history'], previous, feedback, discovery=discovery)
                    plan = discovery.validate(BuildPlan.model_validate(plan))
                except (ValueError, TypeError) as error:
                    if attempt == 0:
                        feedback = f'输出格式或代码约束校验失败，请修正：{str(error)[:1800]}'
                        continue
                    raise ServiceError('模型输出仍不符合方案规范，请补充要求后重试。', 422) from error
                self.store.update(build_id, revision, skill_review=discovery.snapshot())
                body = plan.model_dump()
                history = [*build['history'], {'role': 'assistant', 'content': plan.message}]
                if plan.status == 'needs_input':
                    self.store.update(build_id, revision, status='needs_input', plan=body, history=history)
                    return
                if self.store.update(build_id, revision, status='testing', plan=body) is None:
                    return
                reports = await run_in_threadpool(self.test_plan, plan)
                if all(report['passed'] for report in reports):
                    self.store.update(build_id, revision, status='ready', plan=body, tests=reports,
                                      tested_hash=plan_hash(body), history=history)
                    return
                previous, feedback = body, reports
                self.store.update(build_id, revision, status='generating', tests=reports)
            self.store.update(build_id, revision, status='failed', skill_review=discovery.snapshot(), plan=previous, tests=feedback,
                              error='生成的方法未通过实际测试，尚未发布。可以补充规则重新生成。')
        except ServiceError as error:
            self.store.update(build_id, revision, status='failed', skill_review=discovery.snapshot(), error=str(error))
        except TimeoutError:
            self.store.update(build_id, revision, status='failed', skill_review=discovery.snapshot(), error='模型生成超时，可以稍后重试。')
        except Exception as error:
            # No provider output, source data or credentials in application logs.
            logger.warning('Agent build failed: type=%s', type(error).__name__)
            self.store.update(build_id, revision, status='failed', skill_review=discovery.snapshot(), error='构建未完成，请检查模型连接后重试。')
