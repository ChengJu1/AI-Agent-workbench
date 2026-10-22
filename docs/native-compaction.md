# 双运行时原生压缩

## Deep Agents

`WorkbenchSummarizationMiddleware` 继承 Deep Agents 0.7.19 自己的 `SummarizationMiddleware`，通过 `summary_prompt` 传入平台提示词。平台继续统计摘要调用和用量，并在摘要输入、输出及归档写入处脱敏。摘要不是业务执行依据，审批仍走原来的待确认清单与 ApprovalService。

平台默认在 32000 token 或 80 条消息时触发（两者为 OR），保留最近 12 条。框架按模型 profile 计算的默认值是窗口的 85% 触发、保留 10%；DeepSeek V4 的 profile 窗口为 1000000 token，即约 850000 token 才触发，压缩实际上不会发生，所以平台不采用它。三项都设为 `auto` 才使用框架默认（无 profile 时为 170000 token / 保留 6 条）。只设置触发阈值而保留条数为 `auto` 会被拒绝：框架保留量（窗口的 10%）可能大于触发阈值，导致压缩什么也不删。消息计数使用本地官方 DeepSeek V4 tokenizer，并纳入工具 schema；它不是 provider 的精确计费计数。未知 tokenizer 不进行字符估算，默认另加 80 条消息的触发兜底。

以下配置可覆盖平台默认值，设为 `auto` 表示交给框架：

| 配置 | 用途 |
| --- | --- |
| `WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_TOKENS` | 覆盖 token 触发阈值 |
| `WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_MESSAGES` | 覆盖消息触发条数 |
| `WORKBENCH_DEEPAGENTS_SUMMARY_KEEP_MESSAGES` | 覆盖最近保留条数 |

原文存入该会话转存目录下的 `summary-archive/conversation_history/`，重启后继续追加同一归档。这里的“原文”保留全文信息，但按平台规则脱敏、折行，不承诺字节一致。内部专用后端只允许固定目录的文本新建和追加；目录逐级使用文件描述符与 `O_NOFOLLOW` 打开，拒绝越界和符号链接，文件以临时文件原子替换。归档失败会阻止本次压缩后的模型调用；不能脱敏的二进制媒体不会写入。

只有摘要中间件持有可写后端。模型仍只有会话内的 `ls` / `read_file`，可按摘要给出的路径分页核对归档；不开放 `write_file`、`edit_file`、`execute` 或子 Agent。原生参数截短只处理框架支持的历史 `write_file` / `edit_file` 参数；这些工具在平台中仍禁用，业务工具参数不会因此被截短。

框架保留原始消息的增量 checkpoint，摘要事件只改变送给模型的有效历史。读取完整状态应使用图的 `get_state` / `aget_state`，不能把单条 checkpoint 的 `channel_values` 当成完整消息历史。删除会话同时清理 checkpoint 和该会话归档。

## Claude SDK

已随 Claude SDK 运行时一起移除，见 [单一运行时](single-runtime.md)。

## 每轮硬性要求

两种运行时的结构化任务状态都从平台保存的原始用户消息重新生成 `hard_requirements`，包含当前尚未保存的用户输入。匹配“必须”“不得”“只允许”等明确标记及英文 must / never / only，并保留“硬性要求”“约束”等标题下的列表。记录原文和消息来源，排除助手回复，不依赖模型摘要。

只匹配不易误判的词（必须、务必、不得、禁止、严禁、请勿、切勿、一律、只考虑、只允许、仅限、要求：、must / never / do not），“不要”“不能”“只能”“始终”等口语常见词不算。摘录按原文去重，从最新的消息往前保留，总长不超过 3000 字、单条不超过 800 字；被省略的消息数写入 `hard_requirements_omitted_messages`。这些摘录每轮都会重新发送、不参与压缩，因此必须有上限。

这是显式规则候选摘录，不是完整语义识别；不自动删除旧要求、解决冲突或授予执行权限。没有标记的隐含要求仍由对话和摘要承担。待确认操作与业务版本继续从数据库重新读取。

## 验收

全部使用临时数据库、合成内容与模拟模型，未调用真实模型。新增测试覆盖原生继承与阈值、归档脱敏和分页、路径隔离、写入失败阻断、参数截短边界、图内原始历史保留、重启追加与删除、Claude hook / 边界统计和当前轮要求重注入。

本次回归：后端 407 项，402 项通过、5 项跳过；前端 95 项通过，生产构建通过；依赖检查及差异格式检查通过。

旧阶段的 `runtime-context-synthetic.json` 属于此前实现的历史模拟样例，不能作为当前版本的成本或质量对比结果。真实模型质量和计费对照尚未执行。
