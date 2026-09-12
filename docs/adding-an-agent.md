# 如何新增一个 Agent

本说明面向需要为 AI Agent Workbench 增加新业务场景的开发者。新增 Agent 的核心是增加配置、Prompt、Skill 和工具，而不是复制一套新的 Runtime。

## 一、目录结构

在 `backend/agents` 下为新 Agent 创建独立目录：

```text
backend/agents/example_assistant/
  agent.json
  prompts/
    example.md
  skills/
    example-policy.md
```

目录名建议与 Agent ID 一致，只使用小写字母、数字和下划线。

## 二、编写 Manifest

`agent.json` 需要声明：

- `id`：Agent 的唯一标识。
- `name`：页面展示名称。
- `description`：业务用途。
- `system_prompt`：相对于 Agent 目录的 Prompt 路径。
- `skills`：相对于 Agent 目录的 Skill 文件列表。
- `tools`：Agent 可以使用的工具及 action 白名单。
- `permissions`：默认执行策略和需要人工确认的 action。

MCP Agent 示例：

```json
{
  "id": "example_assistant",
  "name": "示例助理",
  "description": "查询示例业务信息",
  "system_prompt": "prompts/example.md",
  "skills": [
    "skills/example-policy.md"
  ],
  "tools": [
    {
      "type": "mcp",
      "name": "example_server",
      "transport": "stdio",
      "module": "mcp_servers.example_server",
      "actions": [
        "search_example"
      ]
    }
  ],
  "permissions": {
    "dry_run_by_default": true,
    "require_approval": []
  }
}
```

Manifest 中未声明的 action 不会加入模型的允许工具列表。

## 三、编写 System Prompt

System Prompt 应说明：

1. Agent 的身份和职责。
2. 什么情况下调用什么工具。
3. 回答必须包含哪些依据。
4. 工具无结果时如何处理。
5. Agent 不能做什么。
6. 用户要求绕过规则时仍然不能违反边界。

不要在 Prompt 中放真实密钥、内部账号或其他敏感信息。

## 四、编写 Skill

Skill 描述完成业务任务的稳定步骤，例如：

```text
接收用户问题
→ 提取查询主题
→ 调用搜索工具
→ 选择候选结果
→ 获取完整详情
→ 根据工具结果回答
→ 标明信息来源
```

System Prompt 更关注身份和边界，Skill 更关注完成任务的操作流程。

## 五、接入工具

### MCP 工具

在 `backend/mcp_servers` 中创建 FastMCP Server，并使用 `@server.tool()` 注册工具。Manifest 的 `module` 必须指向可以通过下面方式启动的 Python 模块：

```bash
python -m mcp_servers.example_server
```

Manifest 中的 Server 名称和 action 名称必须与代码保持一致。Runtime 会将其转换为：

```text
mcp__example_server__search_example
```

### CLI 工具

CLI 工具需要同时完成：

1. 在 Manifest 中声明 CLI 名称和 action 白名单。
2. 为每个 action 定义参数校验模型。
3. 在 CLI Adapter 中建立 action 与固定命令参数的映射。
4. 禁止让模型自由拼接 Shell 命令。
5. 写操作根据风险加入 `require_approval`。

## 六、启动时发生什么

后端启动时，`AgentRegistry` 会扫描：

```text
backend/agents/*/agent.json
```

随后依次执行：

1. 读取 JSON。
2. 使用 Pydantic 校验 Manifest 字段。
3. 检查 Prompt 和 Skill 路径没有越出 Agent 目录。
4. 读取 Prompt 与 Skill 内容。
5. 创建 `LoadedAgent` 并登记到内存。

如果配置格式错误、文件不存在或者 Agent ID 重复，后端应该直接启动失败，避免带着不完整配置继续运行。

## 七、验证新 Agent

启动后端后依次检查：

1. `/api/agents` 中出现新 Agent。
2. 前端下拉框可以选择新 Agent。
3. Agent 只能看到 Manifest 白名单中的工具。
4. 正常问题能完成工具调用。
5. 无结果时不会编造答案。
6. 工具异常时显示安全提示。
7. 审计日志包含正确的 `tool_type`、action、参数和状态。
8. 原有 Agent 功能没有被破坏。

新增 Agent 时还应增加对应的自动化测试和演示步骤。
