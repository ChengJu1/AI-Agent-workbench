from app.schemas import AgentInfo

AGENTS = [
    AgentInfo(
        id="timesheet_assistant",
        name="工时助理",
        description="帮助团队成员估算工时、整理工时草稿，并支持多轮追问。",
        system_prompt=(
            "你是团队内部的工时助理。你的职责是帮助用户整理工作事项、"
            "估算工时并生成清晰的工时草稿。信息不足时先提出简短的澄清问题；"
            "不要编造用户未提供的工作内容；默认使用简洁中文回答。"
        ),
        permission_mode="default",
        max_turns=3,
    )
]

def list_agents() -> list[AgentInfo]:
    return AGENTS

def get_agent(agent_id: str) -> AgentInfo | None:
    for agent in list_agents():
        if agent.id == agent_id:
            return agent
    return None
