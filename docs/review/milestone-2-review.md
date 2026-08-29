# 里程碑 2 复核

## 结论

**M2 的 mock 核心链路已经跑通，但当前版本还不能算完全通过验收。**

配置加载、受控 CLI、工时草稿、人工确认、取消和审计接口都有实现，后端自动化测试与前端生产构建也通过了。现在还需要修正两个页面验收问题，并补一次真实模型链路。当前 `agent.json` 中的审批配置与实际行为是一致的。

本次复核基于：

- 分支：`function/m2-agent-manifest-cli`
- 当前提交：`41bdc99`（远端同 SHA）
- 对照文档：`docs/milestone-2-agent-manifest-cli.md`

## 已验证通过的内容

| M2 要求 | 结果 | 证据 |
| --- | --- | --- |
| Agent 从配置文件加载 | 通过 | `backend/agents/timesheet_assistant/agent.json` 能被 `AgentRegistry` 读取；`GET /api/agents` 返回“工时助理” |
| Prompt 和 Skill 从文件加载 | 通过 | `prompts/timesheet.md`、`skills/timesheet-policy.md` 被注册并拼接到 Runtime 的 system prompt |
| CLI action 白名单与参数校验 | 通过 | `CliAdapter` 使用配置 action 白名单、Pydantic schema 和参数数组调用 subprocess；没有 `shell=True` |
| 查询日程 | 通过 | mock CLI 查询 `2026-08-27` 返回 3 条日程、总工时 4.5 小时 |
| 生成工时草稿 | mock CLI 通过 | 直接运行 `draft_timesheet` 能返回结构化 records、total_hours 和超时提醒 |
| 提交前人工确认 | 通过 | SDK 工具调用只创建 `pending_actions`，不会直接提交 |
| 确认后模拟提交 | 通过 | API 测试返回 `approved` 和 `submission_id`；重复确认返回 409 |
| 取消后不提交 | 通过 | 取消接口将操作改为 `cancelled`，代码路径不会调用 CLI 提交分支 |
| 审计日志接口 | 通过 | `GET /api/conversations/{id}/audit-logs` 可查到参数、状态、结果/错误和时间 |
| 前端生产构建 | 通过 | `npm ci` 后 `npm run build` 成功 |

## 需要修正的问题

### 1. 确认后前端直接移除卡片，和演示要求不一致

**现象**

点击“确认提交”后，后端确实返回了 `approved` 和 `submission_id`，但页面把这张确认卡片从列表中删除，只在聊天区追加一条成功消息。因此看不到演示文档要求的“卡片状态变为已确认并提交”。取消也会遇到同样的卡片消失行为。

**复现路径**

1. 启动后端和前端，生成一条提交确认卡片。
2. 点击“确认提交”。
3. 查看 `frontend/src/App.tsx` 的 `handleDecision`：219-229 行过滤掉 `updatedAction.id`，没有把更新后的 action 写回列表。
4. 对照 `docs/demo-scripts/m2-demo-script.md` 中“卡片状态变为已确认并提交”的预期。

**影响**

审批接口本身通过，但页面无法展示完整的审批状态和提交编号卡片，人工验收时会表现为卡片突然消失。

**建议**

将 `updatedAction` 替换回原列表项，保留已确认/已取消状态；待确认列表接口可以继续只返回 `pending`，但当前页面状态应保留本次操作结果。

### 2. 流式请求出错后会留下“正在回复...”的空消息

**复现路径**

1. 不配置 `ANTHROPIC_API_KEY`（或临时关闭后端模型服务）。
2. 在页面发送任意消息。
3. 后端会返回 SSE `error` 事件，前端会显示错误提示。
4. 查看 `frontend/src/App.tsx`：129-138 行先插入空的 Agent 消息；182-190 行只在 `streamMessage` 正常返回时删除空消息，191-198 行的异常分支没有清理它。

**影响**

错误提示出现后，聊天区仍会显示永久的“正在回复...”，用户无法区分已经失败还是仍在等待。

**建议**

在异常分支或统一的清理逻辑中删除本次插入的空消息；如果已经收到部分文本，则保留部分文本并标记为失败。

### 3. 权限字段的职责可以再明确（非阻塞）

当前执行逻辑使用 `require_approval` 决定是否拦截提交，`agent.json` 已将 `submit_timesheet` 配置在其中，因此当前版本的配置和行为是一致的，不影响 M2 验收。

`dry_run_by_default` 目前只是被加载，没有单独改变执行结果。后续如果增加更多写操作，可以再明确它与 `require_approval` 的分工；本次不把它算作缺陷。

## 需要在 M2 会议上演示验证的内容

### 真实模型和浏览器端到端链路

当前环境没有有效的 `ANTHROPIC_API_KEY`，所以没有执行真实 DeepSeek/Claude Agent SDK 对话。已经验证缺少密钥时接口会返回 SSE `error` 事件，但这不等于真实模型能完成“查询日程 -> 生成草稿 -> 创建待确认提交”的完整链路。

本次本地浏览器控制组件也未能连接（运行时缓存版本不一致），所以页面问题的证据以源码路径为准，不把它宣称为真实浏览器验收结果。

因此以下内容需要在 M2 会议现场演示确认：

- 模型是否会按 Prompt 正确调用三个工具。
- 真实浏览器中是否能看到流式回复和确认卡片。
- 真实模型多轮上下文中是否能继续使用前一轮草稿。

这不是 M2 mock 功能失败，而是当前没有模型密钥时的验收边界。

## 可重复检查记录

- `git diff --check`：通过。
- 后端：临时 Python 环境执行 `python -m unittest discover -s backend/tests -p 'test_*.py' -v`，7/7 通过。
- 前端：`npm ci --ignore-scripts`、`npm run build`，均通过。
- 后端健康与配置接口：`/api/health` 返回 `{"status":"ok"}`；`/api/agents` 返回配置化的“工时助理”。
- 缺少密钥时的流式接口：HTTP 200 的 SSE 中返回明确的 `缺少 ANTHROPIC_API_KEY` 错误事件。

## 文档和交接问题

- `docs/demo-scripts/m2-demo-script.md` 使用 `.venv/bin/python` 和 `../.venv/bin/uvicorn`，但 `README.md` 的安装步骤是在 `backend/.venv` 创建环境；按 README 新建环境后直接复制 M2 命令会找不到解释器。
- `README.md` 标题和主体仍写着 M1，项目结构仍描述旧的内存会话和内置 Agent，与当前 M2 的 Agent Registry、SQLite 会话存储不一致。

## 项目边界

当前实现仍符合 M2 的 mock 范围：日程、草稿提交都是模拟数据，不连接真实日历或工时系统；只实现一个工时助理；SQLite 适合本地演示，不是生产多实例方案。这些属于文档中明确“不做”的内容，不应当作为 M2 缺陷。
