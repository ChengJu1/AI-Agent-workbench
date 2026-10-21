"""Tool definitions bind the shared business handler, authorization and schema."""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel
from jsonschema import ValidationError, validate


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    arguments: type[BaseModel]
    description: str
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    capability: str | None = None
    schema_override: dict[str, Any] | None = None
    validate_schema: bool = True

    @property
    def schema(self):
        return self.schema_override if self.schema_override is not None else self.arguments.model_json_schema()

    async def invoke(self, arguments):
        # Match the existing MCP schema rejection before entering a business handler.
        # Live authorization, Pydantic parsing and approvals stay in that handler.
        try:
            if self.validate_schema:
                validate(arguments, self.schema)
        except ValidationError as error:
            return {'content': [{'type': 'text', 'text': f'Input validation error: {error.message}'}],
                    'is_error': True}
        return await self.handler(arguments)
