# 自定义 MCP Agent

用户可以在页面中定义 Agent 的名称、用途、提示词及 MCP 工具。后端保存配置，在每轮对话启动 SDK 时注册对应 MCP 服务和所选工具，无需修改 Agent 文件或重启应用。

## 页面操作

1. 点击工具栏中的“创建 Agent”，填写名称、用途和提示词。
2. 为 MCP 连接填写英文名称、服务地址及连接方式。Streamable HTTP 通常使用服务的 `/mcp` 地址，SSE 使用服务提供的 SSE 入口；以实际服务配置为准。
3. 如服务需要 Bearer 认证，填写令牌。认证令牌会保存到当前工作台数据库。
4. 点击“连接并读取工具”，后端执行 MCP 初始化和工具列表查询，不调用业务工具。
5. 选择允许 Agent 使用的工具。每个服务至少选择一个工具，最多配置 10 个服务。
6. 点击“创建并使用”。新 Agent 出现在选择器中并立即选中，可以使用现有聊天和历史会话功能。

工具名称、说明和参数格式由 MCP 服务提供；前端展示发现的定义，保存时传递连接配置和所选工具名称。实际工具仍由 MCP 服务执行。

修改连接地址、连接方式、连接名称或令牌后，会清空该连接已读取和已选择的工具，要求重新连接，避免沿用其他服务的工具列表。

## 接口约定

### 发现工具：`POST /api/mcp/tools`

```json
{
  "name": "team_policy",
  "transport": "http",
  "url": "http://localhost:8059/mcp",
  "headers": {}
}
```

`transport` 支持 `http` 和 `sse`，默认 `http`。认证服务可在 `headers` 中传入 `Authorization` 或服务需要的自定义请求头。

返回工具数组，每项包含 `name`、`description`、`input_schema`。连接失败返回 502，整体发现过程超时返回 504；错误响应不包含服务内部错误或认证信息。发现过程支持分页，并检测重复分页游标。

### 创建 Agent：`POST /api/agents`

```json
{
  "name": "团队制度助理",
  "description": "查询团队制度并提供来源",
  "system_prompt": "使用 MCP 工具查询制度，依据查询结果回答并标注来源。",
  "tools": [
    {
      "type": "mcp",
      "name": "team_policy",
      "transport": "http",
      "url": "http://localhost:8059/mcp",
      "headers": {},
      "actions": ["search_policy"]
    }
  ]
}
```

创建成功返回 201，响应包含 `id`、`name`、`description`，ID 由后端生成。可选 `max_turns` 范围为 1–100，默认 50。重复连接名称、重复工具、空工具列表、无效 URL、控制字符请求头以及未声明的字段返回 422。

配置保存到 `custom_agents` 表；新旧应用实例均从数据库读取，无需内存注册刷新。返回的 Agent 简介和列表不包含提示词、MCP 地址或认证请求头。

创建后使用现有接口：

- `GET /api/agents`：同时返回内置和自定义 Agent 简介。
- `POST /api/conversations`：通过新 Agent ID 创建会话。
- `POST /api/conversations/{id}/messages/stream`：使用该 Agent 的提示词、MCP 配置和工具允许列表回复。
- `GET /api/conversations/{id}/audit-logs`：查看远程 MCP 调用审计。

## 运行与数据边界

- 本版支持创建和使用 Agent；编辑、删除和账号隔离尚未实现，Agent 在当前工作台内共享。
- 用户提交的是 HTTP/SSE MCP 连接配置，不接受前端传来的 Shell 命令、Python 模块或可执行代码。内置 Agent 原有的受控 stdio MCP 配置继续保留。
- 保存配置时校验结构；服务是否在线和工具是否存在由“读取工具”和实际对话验证。
- 远程工具沿用 MCP 服务本身的权限；工时助理专用审批卡片不适用于自定义远程工具。
- 令牌保存在 SQLite 配置中，备份数据库时应一并保护其中的认证信息。
- 服务地址由后端访问。Docker 中的 `localhost` 指向后端容器；连接宿主机服务时，Docker Desktop 通常使用 `host.docker.internal`。本机代理拦截回环连接时，为后端配置 `NO_PROXY=localhost,127.0.0.1,::1`。

## 验证

2026-10-16 验证结果：后端 50 项测试、前端 16 项测试、TypeScript 检查和生产构建均通过。

自动化测试覆盖创建、数据库恢复、会话选择、SDK 配置装配、工具允许列表、输入边界，以及实际 MCP HTTP 初始化和工具列表协议。页面联调使用临时数据库与本机测试 MCP 服务，验证“读取两个工具 → 选择一个 → 创建 → 刷新后保留”；不调用真实模型。
