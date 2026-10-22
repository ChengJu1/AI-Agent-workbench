"""通过 stdio MCP 暴露只读制度工具；实际检索交给 PolicyStore。"""
import logging

from mcp.server.fastmcp import FastMCP
from app.storage.policy_store import PolicyStore

logger = logging.getLogger(__name__)
policy_store = PolicyStore()
policy_server = FastMCP("policy_server")

@policy_server.tool()
def search_policy(query: str):
    """
    - 根据用户关键词搜索相关制度。
    - 返回制度 ID、标题、来源和匹配关键词。
    """
    try:
        return policy_store.search_policy(query)
    except Exception as error:
        logger.exception("制度搜索失败")
        raise RuntimeError("制度查询服务暂时不可用，请稍后重试。") from error

@policy_server.tool()
def get_policy_detail(policy_id: str):
    "通过search_policy返回的制度ID返回完整制度正文"
    try:
        return policy_store.get_policy_detail(policy_id)
    except ValueError as error:
        if str(error) == "制度ID不存在":
            raise ValueError("制度ID不存在，请重新搜索。") from None
        logger.exception("制度详情读取失败")
        raise RuntimeError("制度查询服务暂时不可用，请稍后重试。") from error
    except Exception as error:
        logger.exception("制度详情读取失败")
        raise RuntimeError("制度查询服务暂时不可用，请稍后重试。") from error




if __name__ == "__main__":
    policy_server.run(transport="stdio")
