# 里程碑 2：Agent 配置化与 CLI 工具受控调用

## 周期与验收要求

- 周期：第三周到第四周。
- 验收要求：建议在第四周结束前完成里程碑验收。
- 验收方式：功能演示 + 配置文件检查 + 工具调用日志检查。

## 阶段目标

把 M1 中写死的 Agent 改造成配置驱动，并完成第一个受控 CLI 工具调用闭环。

本阶段的核心演示是“工时助理 Agent”：用户通过自然语言描述需求，Agent 可以调用 mock CLI 查询日程、生成工时草稿，并在用户确认后提交模拟工时。

## 设计思路

本阶段引入 `agent.yaml` 或 `agent.json` 作为 Agent manifest。系统启动时由 Agent Registry 读取配置，然后把系统提示词、工具、Skills 和权限策略传给 Claude Runtime。

CLI 工具必须走受控封装，不允许模型直接执行任意 shell。推荐做法是将 CLI 能力抽象成 action：

1. `query_calendar`：查询模拟日程。
2. `draft_timesheet`：生成工时草稿。
3. `submit_timesheet`：提交模拟工时。

其中 `submit_timesheet` 是敏感动作，必须人工确认。

## Agent 配置示例

```yaml
id: timesheet_assistant
name: 工时助理
description: 帮助团队成员评估工时、生成工时草稿，并在确认后提交模拟工时
system_prompt: prompts/timesheet.md
skills:
  - skills/timesheet-policy.md
tools:
  - type: cli
    name: timesheet_cli
    actions:
      - query_calendar
      - draft_timesheet
      - submit_timesheet
permissions:
  dry_run_by_default: true
  require_approval:
    - submit_timesheet
```

## 模块与目的

1. Agent Registry 模块  
目的：从配置文件加载 Agent，避免每新增一个 Agent 都修改代码。

2. Prompt 与 Skills 加载模块  
目的：将系统提示词和业务规则从代码中拆出来，便于维护。

3. CLI Adapter 模块  
目的：把本地 CLI 包装成结构化、受控、可审计的工具。

4. Approval 模块  
目的：拦截敏感动作，在用户确认后再执行。

5. Audit Log 模块  
目的：记录工具调用、入参、结果、审批状态和错误信息。

## 交付物

1. Agent manifest 配置格式和示例文件。
2. `timesheet_assistant` 配置化实现。
3. 工时助理系统提示词。
4. 工时规则 Skill 文档。
5. mock 工时 CLI 工具。
6. CLI Adapter 受控调用实现。
7. 人工确认接口和前端确认组件。
8. 工具调用审计日志。
9. M2 演示脚本。

## 任务拆解

1. Agent manifest
   - 设计 Agent 配置字段。
   - 实现配置读取和校验。
   - 前端 Agent 列表改为读取后端配置。

2. Prompt 与 Skills
   - 编写 `prompts/timesheet.md`。
   - 编写 `skills/timesheet-policy.md`。
   - 在 Runtime 中按 Agent 加载对应文件。

3. mock CLI
   - 实现 `query_calendar`。
   - 实现 `draft_timesheet`。
   - 实现 `submit_timesheet`。
   - 提供固定 mock 数据，保证演示稳定。

4. CLI Adapter
   - 定义 action 白名单。
   - 定义参数 schema。
   - 使用 subprocess 调用 CLI，禁止 `shell=True`。
   - 捕获 stdout、stderr 和退出码。

5. 人工确认
   - 对 `submit_timesheet` 生成 pending action。
   - 前端展示确认卡片。
   - 用户确认后再执行。
   - 用户取消后记录取消结果。

6. 审计日志
   - 记录 conversation_id、agent_id、tool_name、action、params、status、result、created_at。
   - 前端可以先不做复杂日志页，但后端必须能查询或打印日志。

## 验收标准

1. 新增或修改 Agent 配置后，页面 Agent 列表能正确展示。
2. 工时助理能根据用户描述调用 mock CLI 查询日程。
3. 工时助理能生成工时草稿。
4. 提交工时前必须出现人工确认。
5. 用户确认后才执行模拟提交。
6. 用户取消后不会执行提交。
7. 工具调用日志能看到完整记录。

## 明确不做

1. 不接真实工时系统。
2. 不接真实日历系统。
3. 不做通用 CLI 插件市场。
4. 不支持模型自由执行 shell。
5. 不做复杂权限系统。
