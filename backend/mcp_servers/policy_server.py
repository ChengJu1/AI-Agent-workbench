from mcp.server.fastmcp import FastMCP
from app.services.policy_store import PolicyStore

policy_store = PolicyStore()
policy_server = FastMCP("policy_server")

@policy_server.tool()
def search_policy(query: str):
    """
    - 根据用户关键词搜索相关制度。
    - 返回制度 ID、标题、来源和匹配关键词。
    """
    result = policy_store.search_policy(query)
    return result

@policy_server.tool()
def get_policy_detail(policy_id: str):
    "通过search_policy返回的制度ID返回完整制度正文"
    result = policy_store.get_policy_detail(policy_id)
    return result




if __name__ == "__main__":
    policy_server.run(transport="stdio")
