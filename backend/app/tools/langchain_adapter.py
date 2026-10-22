"""Preserve shared MCP payloads for direct callers and expose proper graph tool errors."""
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool


class SharedLangChainTool(StructuredTool):
    async def ainvoke(self, input, config=None, **kwargs):
        result = await super().ainvoke(input, config=config, **kwargs)
        if isinstance(result, ToolMessage) and isinstance(result.artifact, dict):
            response = result.artifact
            return result.model_copy(update={
                'content': response.get('content', []),
                'status': 'error' if response.get('is_error') or response.get('isError') else 'success',
            })
        return result
