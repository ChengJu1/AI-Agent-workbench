# 阶段 0：运行时用量基线

在 `codex/deepagent` 增加观测，不改模型、工具授权、审批和 Agent 构建器。原有三份未提交文档保持原样。

## 数据与口径

- 每轮数值保存在 `runtime_usage`，会话删除时通过外键级联清理；不保存提示词、工具参数或返回正文。
- 输入、输出、缓存读取与缓存创建 token 使用 SDK `ResultMessage.usage`，字段缺失为 `null`，不冒充零。各字段分别汇总，不假设输入 token 已包含缓存。
- 模型调用数使用 SDK `num_turns`，代表模型轮次，不包含不可见的底层 HTTP 重试；工具调用数按实际 `ToolUseBlock.id` 去重，包含失败调用。
- 首字延迟从本轮进入运行时到首次非空文本 delta；无文本为 `null`。总耗时覆盖运行时配置、生成和工具执行，不包含 SSE 网络传输与用户审批等待。
- 无最终结果的异常或取消也记录统计；未知 token 和模型轮数保持 `null`。统计写入异常不阻断原回复。
- `usage` SSE 事件在原有引用与审批事件之后、`done` 或 `error` 之前发送。前端解析并保存在本轮消息状态中，暂不展示。取消连接时可能无法送达事件，数据库仍记录。

## 上下文构成估算

每轮保存 `context_estimate`，使用随仓库保存的官方 DeepSeek V4 tokenizer 和固定版本 `tokenizers==0.23.3` 在本地统计，不调用模型，也不在运行时下载资源。官方资源、版本、SHA-256 和 MIT 许可证保存在 `backend/resources/tokenizers/deepseek-v4/`。

- 系统提示词：本轮实际系统提示词纯文本，包括业务状态和技能目录。
- 工具说明：本进程 SDK MCP 工具定义的 JSON（名称、说明和参数 schema）；不连接外部 MCP。外部定义或读取失败通过 `tool_descriptions_complete=false` 标记。
- 历史：工作台保存的此前用户和助手纯文本，逐条分词后求和；读取失败为 `null`。SDK 内部历史可能不同。
- 工具返回：本轮观察到的 SDK `ToolResultBlock`，字符串直接分词，结构化内容先序列化 JSON。
- 当前用户消息：单独统计纯文本，避免与历史混淆。

分词使用 `add_special_tokens=False`，不自动添加 BOS/EOS，不套聊天模板。记录 tokenizer 仓库版本、文件校验值、分词库版本及目标模型。支持显式配置的 `deepseek-v4-pro`、`deepseek-v4-flash`（含 `[1m]` 后缀）；未配置、未知模型、资源丢失或依赖不可用时，相关计数为 `null`，并记录状态，**不回退到字符数换算**。使用环境中已有的模型名称，不读取 `.env` 文件。

这些是可观测文本片段的真实分词数，仍不是每轮多次模型请求的计费分摊：SDK 内部历史裁剪、聊天模板、外部工具定义和图片不可完整观测。元数据明确记录覆盖范围，不输出虚假的精确占比。总输入、输出及缓存用量继续以 SDK/API 返回值为准。旧记录保留原有 `method`，报告逐轮展示，避免将旧字符估算与新分词数据混为同一口径。

官方说明：[离线 Token 计算](https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/)。资源来源见随附 `manifest.json`。

## 只读报告

脚本要求显式传入数据库路径，不加载 `.env`，以 SQLite `mode=ro` 和 `query_only` 打开，不初始化数据库，不创建缺失文件。

```sh
cd backend
.venv/bin/python scripts/usage_report.py --database /tmp/synthetic.db --group-by conversation --id 会话ID
.venv/bin/python scripts/usage_report.py --database /tmp/synthetic.db --group-by agent --id AgentID
```

输出每组轮数、各指标总量、各指标有值轮数、平均首字延迟和逐轮上下文估算。没有测到的指标总量为 `null`；部分轮次有值时总量仅包含已测轮次，应结合 `measured_turns` 判断覆盖率。

## 验证

开工基线：后端 316 项（跳过 5 项）；前端 81 项；构建通过。沙箱内两项合成页面测试无法监听本机端口，允许本机监听后全量通过。

新增测试使用模拟 SDK 消息、合成内容和临时 SQLite，覆盖 token 与缓存数值、调用去重、首字时间、未知值、持久化、按会话及 Agent 汇总、只读报告、SSE 分发、失败轮次与原有审批顺序。分词修正另覆盖中英文固定 token ID、断网执行、未知模型和缺失资源。未调用真实模型，未访问真实招聘或第三方站点。
