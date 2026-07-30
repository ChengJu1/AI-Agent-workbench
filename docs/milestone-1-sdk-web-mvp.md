# 里程碑 1：Claude Agent SDK 与 Web 对话通路打通

## 周期与验收要求

- 周期：第一周到第二周。
- 验收要求：建议在第二周结束前完成里程碑验收。
- 验收方式：功能演示 + 代码走读 + 本地启动检查。

## 阶段目标

完成最小可用骨架，打通“Web 页面选择 Agent -> 后端调用 Claude Agent SDK -> 流式返回回复”的主链路。

本阶段不追求工具调用能力，重点是确认 Claude Agent SDK 可以稳定接入 Web 对话系统，并形成后续扩展 Agent、工具和 Skills 的代码结构。

## 设计思路

本阶段采用固定 Agent 配置或内置配置启动系统，先避免过早抽象。后端封装一个 `ClaudeRuntimeService`，前端只关心会话、消息和流式回复。

建议设计：

1. 前端提供单页聊天界面，左侧或顶部展示 Agent 下拉选择。
2. 后端提供 `GET /api/agents` 返回可用 Agent。
3. 后端提供 `POST /api/conversations` 创建会话。
4. 后端提供 `POST /api/conversations/{id}/messages/stream` 发送消息并流式返回。
5. 后端内部使用 Claude Agent SDK client 管理多轮会话。
6. 会话记录先保存在 SQLite 或本地 JSON 文件中。

M1 的关键不是页面漂亮，而是系统分层清楚：Web 层不直接依赖 SDK 细节，SDK 调用逻辑集中封装在 Runtime 层。

## 模块与目的

1. Web 聊天模块  
目的：提供统一对话入口，后续所有 Agent 都在这个页面演示。

2. 后端 API 模块  
目的：承接前端请求，管理 Agent 列表、会话和消息。

3. Claude Runtime 模块  
目的：隔离 Claude Agent SDK 调用细节，避免业务代码散落在接口层。

4. 基础会话存储模块  
目的：支持多轮对话和验收复现，不要求复杂数据库设计。

## 交付物

1. 可运行的前端 Web 聊天页面。
2. 可运行的 FastAPI 后端服务。
3. Claude Agent SDK 调用封装。
4. 至少一个内置 Agent：`timesheet_assistant` 工时助理。
5. 支持流式回复展示。
6. 支持多轮会话 ID。
7. 本地启动说明和 `.env.example`。
8. M1 演示脚本，包含 3 个对话样例。

## 任务拆解

1. 初始化工程结构
   - 创建 `backend` 与 `frontend` 目录。
   - 配置 Python、FastAPI、React、Vite、TypeScript。
   - 提供本地启动命令。

2. 实现后端基础接口
   - `GET /api/health`
   - `GET /api/agents`
   - `POST /api/conversations`
   - `POST /api/conversations/{id}/messages/stream`

3. 封装 Claude Agent SDK
   - 读取 API Key 和必要配置。
   - 封装发送消息和流式响应。
   - 处理 SDK 异常并返回可理解错误。

4. 实现前端聊天页
   - Agent 选择。
   - 消息列表。
   - 输入框。
   - 发送按钮。
   - 加载状态和流式输出。

5. 补充基础文档
   - 本地启动步骤。
   - 环境变量说明。
   - M1 演示路径。

## 验收标准

1. 本地能启动前后端。
2. 页面能看到工时助理 Agent。
3. 用户发送消息后，后端通过 Claude Agent SDK 返回回复。
4. 页面支持流式展示。
5. 同一个会话中可以连续追问。
6. README 或启动文档足够让导师复现。

## 明确不做

1. 不做 CLI 工具调用。
2. 不做 MCP 接入。
3. 不做复杂 Agent 配置解析。
4. 不做登录、权限和用户系统。
5. 不做生产级部署。
