# AI Agent Workbench 里程碑文档

本目录用于管理 `AI Agent Workbench` 实习项目的背景说明、技术边界和 8 周里程碑计划。

项目中文名：AI 工作台  
项目英文名：AI Agent Workbench

## 文档状态

本套文档是新项目的启动版本，只描述后续计划、交付物和验收标准，不记录开发进度，也不沿用其他项目的成果或验收结论。所有任务均以学生从零开始实施为前提。

## 项目背景

团队内部有很多日常协作事项，例如工时评估与提交、内部制度查询、资源或系统权限申请等。这些事项通常分散在不同系统、CLI 工具、审批流程和知识文档中，使用门槛高，重复操作多，也很难让 AI 在安全边界内稳定帮忙。

本项目希望做一个面向团队内部协作场景的 AI 工作台：用户在 Web 对话系统中选择某个业务 Agent，例如“工时助理”或“制度问答助理”，Agent 再基于预先配置的系统提示词、CLI 工具、MCP 工具和 Skills，完成可控、可审计的日常协作任务。

项目不要求从零实现通用 Agent 底座。底层 Agent Loop、工具调用、上下文管理和 MCP 接入能力优先使用 Claude Agent SDK，实习生的重点是完成业务 Agent 的配置装配、Web 对话接入、工具安全封装、人工确认和演示闭环。

更完整的背景说明见：[project-background.md](./project-background.md)。

## 8 周里程碑时间轴

- 项目周期：8 周
- 里程碑周期：每 2 周一个
- M1：第一周到第二周
- M2：第三周到第四周
- M3：第五周到第六周
- M4：第七周到第八周

## 文档索引

1. [项目背景说明](./project-background.md)
2. [推荐技术选型与边界说明](./technical-scope-and-boundary.md)
3. [里程碑 1：Claude Agent SDK 与 Web 对话通路打通](./milestone-1-sdk-web-mvp.md)
4. [里程碑 2：Agent 配置化与 CLI 工具受控调用](./milestone-2-agent-manifest-cli.md)
5. [里程碑 3：MCP、Skills 与完整业务演示闭环](./milestone-3-mcp-skills-demo.md)
6. [里程碑 4：项目复盘与模拟面试](./milestone-4-retrospective-interview.md)
7. [M1 演示脚本](./demo-scripts/m1-demo-script.md)
8. [M2 演示与交接文件](./demo-scripts/m2-demo-script.md)

## 工作节奏说明

本项目按兼职实习节奏设计。每个里程碑都有 2 周时间窗口，但每个阶段只做一条主线，不追求平台化扩展。

每个里程碑的集中验收时间建议控制在半天内，验收内容包括：

1. 功能演示。
2. 代码走读。
3. 遗留问题确认。
4. 下一阶段任务确认。

如果某个功能需要明显超过当前里程碑投入能力，应优先降级为 mock、配置样例或文档说明，不应扩大为生产级实现。

## 最终成果目标

项目结束时应具备以下成果：

1. 一个可运行的 Web 对话系统。
2. 支持在页面中选择不同业务 Agent。
3. 基于 Claude Agent SDK 执行对话和工具调用。
4. 支持通过 Agent 配置文件装配系统提示词、工具和 Skills。
5. 至少完成两个业务 Agent 演示：
   - 工时助理 Agent。
   - 制度信息 QA Agent 或权限申请辅助 Agent。
6. 支持 CLI 工具受控调用、MCP 工具接入、敏感操作人工确认和审计日志。
7. 输出项目复盘、架构说明、简历描述和模拟面试材料。
