# Deep Agents 双运行时（阶段 2—5）

## 当前范围

`DeepAgentsRuntime` 实现统一 `AgentRuntime` 协议。默认仍为 Claude SDK，已有会话升级后全部使用 `claude_sdk`。`build_generator.py` 保持 Claude SDK。

阶段 2 提供流式基础对话和当前会话转存目录的只读访问。阶段 3 已接入授权的平台业务工具、知识库、Skill、审批入口和外部 MCP；没有使用 Deep Agents 的 Skill 中间件。

阶段 4 已接入统一的脱敏转存和自定义摘要。配置、A/B/C 对照及限制见 [上下文管理说明](runtime-context-management.md)。

阶段 5 的默认运行时设置、会话标识、摘要复制和用量历史展示见 [前端与接口说明](runtime-ui.md)。

## 配置与存储

独立配置写在 `backend/.env.example`，实现不会复用 `ANTHROPIC_*`：

| 配置 | 默认值/含义 |
| --- | --- |
| `WORKBENCH_DEEPAGENTS_ENABLED` | `false`，拒绝新建和执行 Deep Agents 对话 |
| `WORKBENCH_DEEPAGENTS_MODEL` | `deepseek-v4-pro` |
| `WORKBENCH_DEEPAGENTS_BASE_URL` | `https://api.deepseek.com` |
| `WORKBENCH_DEEPAGENTS_API_KEY` | 无；不从 Claude 配置回退取值 |
| `WORKBENCH_DEEPAGENTS_CHECKPOINT_PATH` | 主业务库同级的 `deepagents.db` |
| `WORKBENCH_DEEPAGENTS_ARTIFACTS_DIRECTORY` | 主业务库同级的 `runtime-artifacts/` |

生产默认位于 `backend/data/`，数据库及转存目录都被 Git 忽略。临时业务库自动使用同级临时路径；仅构建服务对象不会创建状态库或转存目录。禁止状态库和主业务库使用同一文件；若原业务库恰好叫 `deepagents.db`，默认状态库自动使用 `deepagents-state.db`。测试及外部注入 `services` 时，`create_app` 使用显式设置或默认设置，不额外读取本机 `.env`；生产启动仍按原逻辑读取配置。

SQLite checkpoint 的 `thread_id` 等于会话 UUID。每轮独立打开异步 SQLite 连接，流结束或取消时关闭。新服务实例重建图后读取同一个线程，恢复先前用户/助手消息；本轮系统提示词和结构化任务状态重新生成，不依赖旧消息里的业务状态。

## 会话 API

- `POST /api/conversations` 可传 `runtime: "claude_sdk" | "deep_agents"`；不传时沿用 Claude。Deep Agents 需开关打开。
- 会话列表返回每个会话的 `runtime`。SQLite 字段约束和不可变触发器保证已有会话不能中途换运行时；没有修改运行时的 API。
- `DELETE /api/conversations/{id}` 清除对应 checkpoint、checkpoint writes、转存目录及会话记录。兼容处理旧跟踪表的外键依赖；不会删除其他会话的 checkpoint 或文件，也不删除全局台账和资料档案。
- 回复尚未完成或确认操作处于 `executing` 时拒绝删除。关闭功能开关后，既有 Deep Agents 会话仍可查看和删除，但不能继续执行。

阶段 5 已增加前端选择器、会话标签及用量展示；选择器只在功能启用时出现，已有会话不能中途改变运行时。

## 受限工具与中间件

固定 Deep Agents 0.7.19 的原因：该版本支持 filesystem 工具白名单和明确禁用默认 general-purpose 子 Agent 的 harness profile。`subagents=[]` 本身仍会自动添加默认子 Agent，因此实现显式设置 `GeneralPurposeSubagentProfile(enabled=False)`，并测试模型实际绑定的工具列表。

- 文件系统工具只有 `ls`、`read_file`，另有按 Agent 授权注册的共享业务工具；`task`、`write_file`、`edit_file`、`execute` 等不在工具节点中。
- `SessionReadOnlyBackend` 只实现列目录和分片读取 UTF-8 文本；父类写入、编辑、删除方法均不可用，没有命令执行实现。
- 目录按会话 UUID 隔离。路径通过目录文件描述符逐段打开，并使用 `O_NOFOLLOW` 拒绝符号链接，拒绝 `..`、`~` 等路径。列目录不展示符号链接，不向模型返回宿主绝对路径错误。
- 仍禁用框架默认摘要中间件和工具/用户消息自动转存。阶段 4 通过自定义中间件提供明确阈值的摘要，写入由共享脱敏转存逻辑控制。
- 未传入 `interrupt_on`，也没有新的审批机制。

## 流与用量

LangGraph `messages` 映射为 `delta`；`updates` 映射工具开始/结束及成功/失败。工具状态只含工具名称、调用 ID 和成功标志，不包含参数及工具原文。最终 `done` 继续由会话服务发送；错误使用安全文本，部分回复仍保存，锁会释放。

用量继续保存到 `runtime_usage`，标注 `runtime=deep_agents`。输入/输出及缓存来自 LangChain 的 `usage_metadata`，模型轮数、工具调用数及耗时独立记录。缺少任一模型轮的 token 数据时不声称已得到整轮总量。提示词/当前用户消息使用既有官方离线 tokenizer；图内部历史、middleware 文本和工具 schema 未完整观测的部分明确为未知。

## 依赖锁定

`backend/requirements.txt` 固定：

- `deepagents==0.7.19`：上述受限 middleware/profile 行为。
- `langgraph==1.2.16`、`langgraph-checkpoint-sqlite==3.1.2`：多模式流式输出和 SQLite checkpoint 读写/删除 API。
- `langchain-deepseek==1.1.1`：独立 DeepSeek 模型配置。
- `langchain-mcp-adapters==0.3.2`：阶段 3 外部 MCP 使用官方工具转换器。
- 同时固定实际验收的 LangChain Core、LangChain、checkpoint 和 prebuilt 版本，避免关键接口随依赖解析漂移。

阶段 1 的 LangChain 工具契约测试已纳入默认测试发现。

## 验证

所有模型使用 LangChain `FakeListChatModel` 或它的确定性工具调用子类，数据和数据库均为临时合成内容；没有调用真实模型。真实模型验收仍需用户明确同意。

```sh
cd backend
LANGSMITH_TRACING=false .venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m pip check

cd ../frontend
PATH=/usr/local/bin:$PATH npm test
PATH=/usr/local/bin:$PATH npm run build
```

`test_deep_agents.py` 覆盖流式输出、实际工具白名单、新服务实例恢复、同一线程标识、删除与其他会话隔离、旧库升级、运行时不可修改、功能开关关闭、独立模型配置、部分失败和取消清理、工具状态及路径越界/符号链接拒绝。

本阶段最终验收：后端 355 项（跳过 5 项，其余通过），前端 84 项通过，构建通过，`pip check` 无依赖冲突；构建保留原有包体积提示。阶段 0、1 已以 `16e2f58` 提交并快进合回原分支，阶段 2 尚未提交。
