"""Shared validated invocation used by independent per-package MCP processes."""
from jsonschema import Draft202012Validator, ValidationError
from app.capabilities.sandbox import CodeSandbox
from app.errors import ServiceError
from app.models.builds import BuildPlan
from app.storage.agent_store import AgentStore
from app.storage.build_store import BuildStore


class PackageExecutor:
    def __init__(self, database, package_id, version, agent_id, sandbox=None):
        self.database = database
        self.package_id = package_id
        self.version = version
        self.agent_id = agent_id
        self.sandbox = sandbox or CodeSandbox()
        self.plan = self.load()

    def load(self):
        agent = AgentStore(self.database).get(self.agent_id)
        if agent is None or not any(ref.package_id == self.package_id and ref.version == self.version for ref in agent.generated_tools):
            raise ServiceError('Agent 未绑定此能力包版本。', 403)
        package = BuildStore(self.database).package(self.package_id, self.version)
        return BuildPlan.model_validate(package['plan'])

    def execute(self, name, arguments):
        # Recheck binding and immutable source hash at every invocation.
        plan = self.load()
        method = next((tool for tool in plan.tools if tool.name == name), None)
        if method is None:
            raise ServiceError('方法不存在。', 404)
        try:
            Draft202012Validator(method.input_schema).validate(arguments)
        except ValidationError as error:
            raise ServiceError(f'参数不符合方法约定：{error.message[:400]}', 422) from error
        result = self.sandbox.execute(method.code, arguments)
        try:
            Draft202012Validator(method.output_schema).validate(result)
        except ValidationError as error:
            raise ServiceError('方法结果不符合已发布的输出约定。', 422) from error
        return result
