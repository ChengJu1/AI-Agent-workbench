import asyncio
import os
import tempfile
from pathlib import Path
from app.config import Settings
from app.services.agent_registry import AgentRegistry
from app.services.claude_runtime import ClaudeRuntimeService
from app.storage.database import Database
from app.storage.conversation_store import ConversationStore
from app.storage.tool_store import ToolStore

async def main():
    Settings.from_env()
    with tempfile.TemporaryDirectory(prefix='workbench-session-check-') as folder:
        db = Database(Path(folder) / 'test.db')
        db.initialize()
        store, audit = ConversationStore(db), ToolStore(db)
        agent = AgentRegistry().get_agent('policy_qa_assistant')
        cid = store.create(agent.id)
        store.add_message(cid, 'user', '这是合成验收历史：我想了解 GPU 资源制度。')
        store.add_message(cid, 'assistant', '可以查询制度；没有执行任何申请。')
        runtime = ClaudeRuntimeService(audit_store=audit)
        events = []
        async for event in runtime.stream_reply(cid, agent,
            '这是合成修复验收。请用 search_policy 搜索 GPU，然后读取命中的制度详情，简短返回制度名称。不要创建或提交申请。',
            True):
            events.append(event)
        logs = audit.get_audit_logs(cid)
        print({'reply_chars':sum(len(e.get('content','')) for e in events if e['type']=='delta'),
               'mcp_calls':[{'action':x['action'],'status':x['status']} for x in logs],
               'history_messages_preserved':len(store.get_messages(cid))})
        assert any(x['action']=='search_policy' and x['status']=='success' for x in logs)
        assert any(e['type']=='delta' for e in events)

asyncio.run(main())
