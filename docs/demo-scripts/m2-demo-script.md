# M2 演示与交接文件

本文件用于交接和验收 M2 的 Agent 配置化、CLI 受控调用、人工确认与审计日志闭环。

## 一、M2 已交付范围

1. `timesheet_assistant` 改为由 `agent.json`、Prompt 和 Skill 文件驱动。
2. 实现 `query_calendar`、`draft_timesheet`、`submit_timesheet` 三个 mock CLI action。
3. CLI Adapter 负责 action 白名单、参数校验和固定 subprocess 调用，不允许模型自由执行 Shell。
4. `submit_timesheet` 只创建 Pending Action，用户确认后才真正执行模拟提交。
5. SQLite 保存会话、消息、Pending Action 和工具审计日志。
6. 前端可以展示工时确认卡片，并支持确认或取消。
7. 提供自动化测试和命令行演示脚本。

## 二、演示前准备

### 1. 检查后端环境

确认 `backend/.env` 已配置有效的 `ANTHROPIC_API_KEY`。

不要提交 `.env`。项目的 `.gitignore` 已忽略该文件。

### 2. 启动后端

在项目根目录执行：

```bash
cd backend
../.venv/bin/uvicorn app.main:app --reload
```

浏览器访问 `http://127.0.0.1:8000/api/health`，预期得到：

```json
{
  "status": "ok"
}
```

### 3. 启动前端

新开一个终端，在项目根目录执行：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`，确认 Agent 下拉框显示“工时助理”。

### 4. 打开调试工具

打开浏览器开发者工具的 Network 面板，重点观察：

- `messages/stream`
- `pending-actions`
- `decision`
- `audit-logs`

## 三、样例一：验证配置化 Agent

访问：

```text
http://127.0.0.1:8000/api/agents
```

预期返回的 Agent 信息来自：

```text
backend/agents/timesheet_assistant/agent.json
```

预期页面显示：

```text
工时助理
```

这一步用于验证 Agent Registry 已经替代 M1 中写死的 Agent 数组。

## 四、样例二：查询日程并生成工时草稿

在页面输入：

```text
请查询 2026-08-27 的日程，并根据日程生成工时草稿。
```

预期：

1. Agent 调用 `query_calendar` 查询固定 mock 日程。
2. Agent 调用 `draft_timesheet` 生成结构化草稿。
3. 草稿包含以下三项：
   - 项目晨会：1 小时。
   - 需求评审：1.5 小时。
   - 接口开发：2 小时。
4. 总工时为 4.5 小时。
5. 本步骤不会提交工时，也不会出现提交成功提示。

## 五、样例三：确认后提交模拟工时

在同一会话继续输入：

```text
请提交刚才生成的工时草稿。
```

预期：

1. Agent 调用 `submit_timesheet` 后，后端只创建状态为 `pending` 的操作。
2. 页面出现“工时提交确认”卡片，显示事项、日期、时长和总工时。
3. 在用户点击按钮前，不会执行模拟提交。
4. 点击“确认提交”。
5. 卡片状态变为“已确认并提交”。
6. 页面显示 `submission_id`，Pending Action 状态变为 `approved`。

这一步用于验证模型不能绕过人工确认直接执行敏感操作。

## 六、样例四：取消后不执行提交

继续让 Agent 生成另一份提交申请，然后在确认卡片中点击“取消”。

预期：

1. Pending Action 状态从 `pending` 变为 `cancelled`。
2. 不会生成新的 `submission_id`。
3. 不会执行 `submit_timesheet` CLI 的确认提交分支。
4. 审计日志会记录一条 `cancelled` 状态。

## 七、检查审计日志

从 Network 面板或浏览器 Local Storage 中取得当前 `conversation_id`，然后访问：

```text
http://127.0.0.1:8000/api/conversations/<conversation_id>/audit-logs
```

确认日志中包含：

1. `conversation_id`
2. `agent_id`
3. `tool_name`
4. `action`
5. `params`
6. `status`
7. `result` 或 `error`
8. `created_at`

成功提交的完整状态应包含：

```text
query_calendar    success
draft_timesheet   success
submit_timesheet  pending
submit_timesheet  approved
```

取消提交时应包含：

```text
submit_timesheet  pending
submit_timesheet  cancelled
```

## 八、自动化检查

### 后端测试

在项目根目录执行：

```bash
.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py' -v
```

当前包含 7 个测试，覆盖：

- CLI 白名单与审批拦截。
- SDK 工具注册与调用。
- 确认和取消接口。
- 审计日志接口。
- SSE 审批事件。

### 前端构建

```bash
cd frontend
npm run build
```

### 命令行完整演示

先启动后端，然后在项目根目录执行确认流程：

```bash
.venv/bin/python backend/scripts/m2_demo.py --decision approve
```

执行取消流程：

```bash
.venv/bin/python backend/scripts/m2_demo.py --decision cancel
```

## 九、关键文件交接

```text
backend/agents/timesheet_assistant/agent.json       Agent Manifest
backend/agents/timesheet_assistant/prompts/         System Prompt
backend/agents/timesheet_assistant/skills/          工时业务规则
backend/app/agent_manifest.py                       Manifest 数据校验
backend/app/services/agent_registry.py              Agent 配置加载
backend/tools/timesheet_cli.py                      mock CLI
backend/app/tool_schemas.py                         CLI 参数校验
backend/app/services/cli_adapter.py                 CLI 安全调用
backend/app/services/timesheet_tools.py             Claude SDK 工具注册
backend/app/services/tool_store.py                  Pending Action 与审计存储
backend/app/services/claude_runtime.py               Claude Runtime
backend/app/main.py                                  审批、审计与 SSE API
frontend/src/App.tsx                                 聊天和确认卡片
frontend/src/api.ts                                  前后端通信
backend/tests/test_m2.py                             M2 自动化测试
backend/scripts/m2_demo.py                           M2 命令行演示
```

## 十、当前边界

1. 日程和提交均为 mock，不连接真实业务系统。
2. 当前只实现一个工时助理 Agent，不做通用 CLI 插件市场。
3. SQLite 适合本地演示，不是生产级多实例数据库方案。
4. `max_turns` 当前设置为 8，用于支持查询、草稿、提交申请和最终回答。
5. 前端暂时没有复杂审计日志页面，通过后端接口或数据库查看日志。

## 十一、M2 验收清单

- [ ] 页面正确展示配置化 Agent。
- [ ] Agent 能调用 mock CLI 查询日程。
- [ ] Agent 能生成结构化工时草稿。
- [ ] 提交前出现人工确认卡片。
- [ ] 确认后才执行模拟提交。
- [ ] 取消后不会执行提交。
- [ ] 审计日志包含完整调用记录。
- [ ] 后端自动化测试通过。
- [ ] 前端生产构建通过。
