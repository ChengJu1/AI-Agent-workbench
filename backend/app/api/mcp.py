"""发现用户指定的远程 MCP 服务工具，供前端选择允许调用的工具。"""
from fastapi import APIRouter, Depends

from app.api.dependencies import get_services
from app.models.agents import McpConnection
from app.models.api import McpToolInfo


router = APIRouter(prefix="/api/mcp")


@router.post("/tools", response_model=list[McpToolInfo])
async def discover_tools(connection: McpConnection, services=Depends(get_services)):
    return await services.mcp_discovery.list_tools(connection)
