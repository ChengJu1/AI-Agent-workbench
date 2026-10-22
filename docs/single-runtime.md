# 单一运行时：只保留 Deep Agents

平台曾同时支持 Claude Agent SDK 与 Deep Agents 两个运行时。经真实模型对比（同一服务商、同一模型、5 个自动判分任务各 2 遍），两者回答质量基本打平；Deep Agents 的循环、压缩和工具都可以在平台内定制，后续团队、自定义流程也只能在它与 LangGraph 上实现，因此只保留 Deep Agents。

最后一个双运行时版本是 Git 标签 `dual-runtime-final`，需要时可以从那里找回 Claude SDK 运行时、对比脚本和相关测试。

## 变化

| 方面 | 现在 |
| --- | --- |
| 模型连接 | 只用 `WORKBENCH_DEEPAGENTS_API_KEY`（可选 `_MODEL`、`_BASE_URL`、`_REASONING_EFFORT`）；`ANTHROPIC_*` 不再读取 |
| 启用开关 | `WORKBENCH_DEEPAGENTS_ENABLED` 已移除，设置了也会被忽略 |
| Agent 构建助手 | 改用 LangChain `create_agent` 和同一模型连接；仍只有只读的 Skill 搜索与读取工具 |
| 新会话 | 一律使用 Deep Agents，创建接口不再接受 `runtime` |
| 旧的 Claude SDK 会话 | 只读归档：消息照常显示，列表标注“只读”；发消息或确认后续跑返回 409，可以删除 |
| 已删除的接口 | `GET /api/runtime-options`、`PUT /api/agents/{id}/runtime`、`GET /api/conversations/{id}/work-summary`、`POST /api/conversations/{id}/copy-summary` |
| 已删除的界面 | 默认运行时设置、新会话“高级”运行时选项、复制工作摘要到新会话、会话运行时标签 |
| 已删除的配置 | `WORKBENCH_CLAUDE_RESULT_OFFLOAD_ENABLED`、`WORKBENCH_CLAUDE_AUTO_COMPACT_WINDOW_TOKENS`、`WORKBENCH_CLAUDE_AUTO_COMPACT_PCT` |
| 依赖 | 移除 `claude-agent-sdk` |

旧会话之所以不能继续：它们的模型上下文保存在 Claude Code 自己的会话文件里，Deep Agents 读不到。数据库里的 `runtime` 字段仍保留 `claude_sdk` 取值，用来识别这些归档会话。

## 测试

原先借 Claude SDK 调用链测试平台功能的用例（审批、知识库与笔记依据、Skill 读取、外部 MCP 审计、确认后续跑等）已改为通过 Deep Agents 运行。测试用的假模型在 `backend/tests/scripted_turn.py`：按剧本发出工具调用，再根据工具的真实返回生成回答；`backend/tests/mcp_test_server.py` 把共享工具定义包装成 MCP 服务，供需要按协议调用工具的测试使用。只针对 Claude SDK 内部行为的测试（会话恢复、SDK 错误码、Claude 压缩钩子与用量统计）已删除。
