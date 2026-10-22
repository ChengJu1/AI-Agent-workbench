# 阶段 1：共享运行时与工具边界

> 历史文档：描述的是双运行时阶段的设计，Claude SDK 运行时已移除，见 [单一运行时](single-runtime.md)。

## 实现

- `app/runtime/contracts.py` 定义 `AgentRuntime`、`RuntimeContext` 和 `RuntimeEvent`；事件保留既有字段。`ConversationService` 只调用 `stream(..., context)`，仍负责保存回复、发送最终 `done` 和安全错误。
- `ClaudeRuntimeService` 实现新协议。`stream_reply` 保留为兼容入口；`delete_conversation` 使用 SDK 的 `delete_session`，明确限定后端项目目录，并容忍会话已不存在。当前没有新增删除 API，阶段 2 再接入完整会话删除流程。
- `app/runtime/prompts.py` 保存共享提示词。原有提示词和审批要求原样搬移；Agent 构建器 `build_generator.py` 不变，继续使用 Claude SDK。
- `app/tools/registry.py` 定义名称、Pydantic 参数模型、说明、处理函数、所需平台能力和可选 JSON Schema。平台、知识库、Skill、工时以及构建器 Skill 发现复用这些定义。
- `app/tools/runtime_adapters.py` 提供 `to_claude_sdk` 和惰性导入的 `to_langchain`，后者可按 MCP 服务名加命名空间。参数 JSON Schema 校验在共享定义中，业务 Pydantic 校验、动态授权复核、审批、引用和审计留在共享处理函数。SDK 自带的同等 schema 拒绝保持原有文字；不合 schema 的参数在进入业务工具前被拒绝，与既有行为一致。

## MCP 审计与笔记引用

过去靠模型的 `AssistantMessage` / `UserMessage` 推断外部工具是否执行。现在由 `app/tools/external_tools.py` 包住实际调用：

1. SDK 仍看到原 MCP 服务名和工具名，只有 Manifest 允许的工具进入列表。转发时保留上游工具元数据与结果内容。
2. stdio / HTTP / SSE 连接按轮惰性打开；同一服务的一轮调用复用连接。一个连接所有者任务管理连接生命周期，并支持并行工具请求；取消或本轮结束时清理。
3. 共享 `McpAuditTracker.execute` 在实际工具调用的成功、失败和取消边界记录审计；`NotesEvidenceTracker` 在同一处理边界保存笔记证据。两者都不导入 SDK 消息类型。
4. 知识库和 Skill 原本就由业务函数记录引用、版本和预算，保持该机制。
5. 只有模型消息中出现“调用/返回”的内容不再能生成审计或引用；测试改为经过真实的工具处理路径。这是把审计依据从模型叙述改为实际执行所必需的变化。

外部 MCP 的配置构造接口保持不变；实际发起 SDK 查询时转换为受控的本进程 MCP 转发服务。未调用模型测试只连接合成或内存 MCP 服务，不访问真实外部服务。

## 每轮任务状态

`TaskContextBuilder.build_task_context(conversation_id, agent)` 每轮从数据库重建：

- 既有工时审批结果和跟踪事项摘要；
- 当前会话、当前 Agent 的待确认及执行中操作 ID、工具名和状态，不注入操作原始参数；
- 仅对有 `applications` 权限的 Agent 注入台账 ID、revision、stage、公司和岗位，以及资料档案最新版本和用户审阅版本，不注入资料正文。台账最多 100 条并附总数，完整详情仍用工具读取；
- 当前系统没有单独存储用户硬性要求，明确标注 `hard_requirements_status=not_stored`，不从聊天中猜测要求或授权。

状态 JSON 明确作为资料，不授予执行权限。原有审批状态仍由数据库及 `ApprovalService` 决定。没有新增 `interrupt_on`、子 Agent、文件写入或命令执行能力。

## 验证方法

常规全量测试：

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -q
```

`test_runtime_contract.py` 固定阶段 0 的普通回答、知识库引用、待确认、出错事件序列，验证实际引用快照、待确认操作不执行、只依赖统一协议、每轮刷新版本和权限范围。`test_external_tools.py` 验证惰性连接、连接复用/清理、白名单、参数拒绝、失败脱敏、取消审计和真实 stdio 合成 echo 服务。

LangChain 适配器单独在临时环境验证，避免提前给主项目引入阶段 2 依赖。安装 `langchain-core==1.6.5` 后，显式运行：

```sh
# 使用同时可导入项目依赖与 LangChain Core 的 Python 环境
LANGSMITH_TRACING=false python -m unittest discover -s tests -p test_langchain_tool_contract.py -q
```

三个测试验证两种适配器的成功结果、失败结果、参数拒绝、Skill 预算及授权撤销一致。没有调用真实模型或 LangSmith，也没有部署真实 MCP 服务。阶段 2 已将文件改为 test_ 前缀，适配器测试随默认全量测试一起运行。

前端未做阶段 1 改动，新增工具状态事件仅定义协议，暂不发送，保留既有事件顺序。
