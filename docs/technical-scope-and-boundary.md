# 推荐技术选型与边界说明

## 1. 推荐技术选型

以下技术栈是本项目的默认推荐方案，目的是降低上手成本、减少工程变量，并保证 8 周内可以完成可演示闭环。

如果实习生有更合适的技术方案，可以单独提出。提出时需要说明：

1. 为什么推荐替换默认方案。
2. 新方案能带来什么明确收益。
3. 对开发进度、演示闭环和维护成本有什么影响。
4. 是否会引入新的学习成本或集成风险。

技术选型可以讨论和调整，但需要先确认再实施，避免中途频繁换栈导致时间失控。

### 后端推荐方案

- Python 3.11+
- FastAPI
- Claude Agent SDK Python
- Pydantic
- SQLite 或本地 JSON 文件存储
- Uvicorn

推荐原因：

1. Python 生态成熟，适合快速搭建 Agent 原型。
2. FastAPI 适合快速构建 Web API 和流式接口。
3. Claude Agent SDK 负责底层 Agent Loop、工具调用和 MCP 接入。
4. SQLite 或本地 JSON 足够支撑原型演示，避免数据库运维消耗时间。

### 前端推荐方案

- React
- Vite
- TypeScript
- SSE 或 WebSocket 用于流式消息展示

推荐原因：

1. 实现成本低，适合构建演示型 Web 对话系统。
2. 页面结构简单，核心是 Agent 选择、聊天窗口、工具调用状态和人工确认。

### 工具与集成推荐方案

- CLI 工具：优先使用本地 mock CLI。
- MCP 工具：优先使用本地 mock MCP server。
- Skills：使用项目内 Markdown 文件或 Claude Agent SDK 支持的 Skills 目录组织。
- 日志：使用本地文件或 SQLite 表记录工具调用和审批结果。

以上方案不是为了限制技术发挥，而是为了保证实习项目可以稳定交付。若选择其他方案，应优先保证主流程不变：Web 对话、Agent 选择、Claude Agent SDK Runtime、CLI/MCP 工具接入、人工确认和审计日志。

## 2. 系统模块边界

MVP 阶段建议优先实现以下核心模块：

1. Web 对话模块  
提供 Agent 选择、消息输入、流式回复展示、工具调用状态展示和人工确认入口。

2. Agent Registry 模块  
读取 Agent 配置文件，返回可用 Agent 列表，并为运行时提供系统提示词、工具、Skills 和权限策略。

3. Claude Runtime 模块  
封装 Claude Agent SDK，负责创建会话、发送用户消息、处理流式输出和绑定工具。

4. Tool Adapter 模块  
把 CLI 和 MCP 能力包装成受控工具。CLI 工具必须通过白名单 action 调用，不允许模型自由拼 shell 命令。

5. Approval 模块  
对敏感动作进行人工确认，例如提交工时、发起权限申请草稿等。

6. Audit Log 模块  
记录每次工具调用、入参、结果、审批状态和错误信息。

## 3. Agent 配置边界

Agent 配置文件建议采用 YAML 或 JSON。最小字段如下：

```yaml
id: timesheet_assistant
name: 工时助理
description: 帮助团队成员评估工时、生成工时草稿并在确认后提交模拟工时
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

MVP 阶段建议只支持单层配置，不优先实现复杂继承、远程配置中心、可视化编排器或插件市场。若实习生认为某个配置能力对演示闭环非常关键，可以单独说明后再确认是否纳入范围。

## 4. 工具调用安全边界

工具调用涉及内部系统安全，本节属于项目安全底线，不建议随意放宽：

1. 不允许把通用 shell 直接暴露给模型。
2. CLI 工具必须通过 action 白名单调用。
3. CLI 参数必须经过 schema 校验。
4. Python subprocess 调用禁止使用 `shell=True`。
5. 所有写操作默认 dry-run。
6. 敏感动作必须走人工确认。
7. 工具调用必须写审计日志。
8. 真实内部系统只允许使用 mock 或沙箱数据，不允许直接操作生产环境。

## 5. 功能范围

### MVP 必达能力

1. Web 页面可以选择 Agent。
2. Web 页面可以与选定 Agent 多轮对话。
3. 后端通过 Claude Agent SDK 调用模型。
4. 至少一个 Agent 通过配置文件生成。
5. 至少一个 CLI mock 工具完成受控调用。
6. 至少一个 MCP mock 工具完成接入演示。
7. 至少一个敏感动作需要人工确认。
8. 至少两个业务 Agent 能完成演示。
9. 有审计日志和演示脚本。

### 可降级实现

1. 数据存储可以从 SQLite 降级为 JSON 文件。
2. MCP server 可以使用最小 mock，不要求接真实内部系统。
3. Skills 可以先用 Markdown 文件加载，不要求完整技能市场。
4. 权限申请 Agent 可以只生成申请草稿，不要求真实提交。

### 默认不做，除非单独确认

1. 不做企业 SSO。
2. 不做完整 RBAC 权限系统。
3. 不做多租户隔离。
4. 不做真实工时系统接入。
5. 不做真实审批系统接入。
6. 不做插件市场。
7. 不做复杂 RAG 平台。
8. 不做移动端适配。
9. 不做浏览器插件。
10. 不重新实现通用 Agent Runtime。

## 6. 时间控制规则

本项目是兼职实习项目，应优先保证演示闭环。

遇到以下情况建议立即收窄范围，或先和导师确认：

1. 单个功能连续投入超过 2 小时仍未跑通。
2. 需要接入真实内部系统账号或权限。
3. 需要研究大量 SDK 内部实现。
4. 前端交互细节开始影响主流程交付。
5. 为了“更通用”而增加抽象层。

推荐处理方式：

1. 先用 mock 数据跑通。
2. 先写固定配置，再提取通用结构。
3. 先完成一个 Agent，再复制扩展第二个 Agent。
4. 先完成成功路径，再补充错误处理。
5. 先实现本地演示，再考虑部署。

## 7. 成功标准

项目成功不以功能数量判断，而以以下标准判断：

1. 实习生能清楚解释为什么使用 Claude Agent SDK。
2. 实习生能清楚解释 Agent 配置如何扩展新业务。
3. 实习生能清楚解释 CLI 工具为什么不能直接暴露 shell。
4. 实习生能演示人工确认和审计日志。
5. 实习生能从架构、安全和业务价值三个角度讲清楚项目。
