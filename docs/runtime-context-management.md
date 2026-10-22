# 阶段 4：上下文管理与模拟对照

> 历史文档：描述的是双运行时阶段的设计，Claude SDK 运行时已移除，见 [单一运行时](single-runtime.md)。

> 本文保留阶段 4 的历史验收数据。当前原生压缩、自动阈值、会话归档及每轮硬性要求机制见 [双运行时原生压缩](native-compaction.md)。

阶段 4 实现共享的大工具结果转存和 Deep Agents 对话摘要，准备了 A/B/C 离线对照脚本。默认仍使用 Claude 原有返回策略；Deep Agents 总开关和 Claude 对照转存开关默认均为 false。没有调用真实模型，也没有访问真实招聘网站。

## 三组配置

| 组 | 运行时 | 大结果策略 | 对话摘要 |
| --- | --- | --- | --- |
| A | Claude SDK | 原样返回 | 沿用 SDK 现状，不新增 |
| B | Claude SDK | 共享脱敏转存、精简返回、按需读回 | 不新增 |
| C | Deep Agents | 与 B 同一套策略 | 明确阈值的自定义摘要中间件 |

配置在 `backend/.env.example` 中，独立的状态与转存路径继续沿用阶段 2 配置。

| 配置 | 默认值 |
| --- | --- |
| `WORKBENCH_CLAUDE_RESULT_OFFLOAD_ENABLED` | `false`，开启才进入 B 组 |
| `WORKBENCH_TOOL_RESULT_OFFLOAD_CHARS` | `4000`，对工具响应 JSON 字符数判断，严格超过才转存 |
| `WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_TOKENS` | `32000`；三项都为 `auto` 时按模型自动调整 |
| `WORKBENCH_DEEPAGENTS_SUMMARY_TRIGGER_MESSAGES` | `80`，与 token 阈值为 OR 关系 |
| `WORKBENCH_DEEPAGENTS_SUMMARY_KEEP_MESSAGES` | `12`；设置触发阈值时不能为 `auto` |

数值必须为正整数，保留条数必须小于消息触发条数。生产默认转存目录是 `backend/data/runtime-artifacts/<conversation UUID>/`，临时数据库使用同级临时目录。

## 转存与读回

`app/runtime/result_offload.py` 在共享业务处理、审计和引用捕获之后转换模型可见响应，所以原有待确认清单、引用快照及资料版本校验不依赖精简预览。只改变返回策略，不改变业务处理层。

- 使用现有 `redact(..., limit=None)` 规则脱敏。MCP 文本中的 JSON 先解析，使 token/password 等字段也能按键名隐藏；电话号码、邮箱、身份证号和 URL 授权参数沿用已有规则。不会把未脱敏全文放入预览或日志。
- 文件保留按已有脱敏规则处理后的完整内容。长行按 1000 字符折行，因此这是可分页阅读的文本，不承诺是可重新解析或执行的 JSON。
- 返回有限预览、会话内路径、字符数、总行数及不完整提示；保留失败标志。模型需要细节时按路径读回，不得把预览当作完整结果。
- Claude B 只新增 `mcp__workbench_artifacts__ls` / `read_file`；C 使用原来的只读 `ls` / `read_file`。模型不能写入、编辑、执行或选择宿主路径。写入由内部固定策略负责，不通过模型文件工具。
- UUID 会话目录、随机文件名、排他创建和不跟随符号链接，避免跨会话或覆盖文件。读回最多 100 行且不超过 20000 字符，返回下一行偏移；大于 4 MB 的转存文件仍可分页读取。
- 读回结果不再次转存，避免产生引用循环。转存失败返回安全错误，提醒核对操作状态，不自动重放有副作用的动作；失败写入不会留下部分文件。
- 删除 Claude B 或 C 会话时清理其转存文件；其他会话不受影响。

## 摘要与关键状态

`app/runtime/context_summary.py` 继承 Deep Agents 的 `SummarizationMiddleware` 并接入图，替换未定制的默认实例。平台传入摘要提示词、统计用量并脱敏；专用内部后端把历史写入会话 `summary-archive/`，模型文件后端仍只读。摘要只调用独立 DeepSeek 配置对应的模型；测试注入确定性模拟模型。没有子 Agent、SkillsMiddleware、命令执行或新的审批机制。

本地消息计数使用既有官方离线 DeepSeek V4 tokenizer，对明确的消息 JSON 表示计数；没有按字符比例估算。它不是 provider 完整聊天模板的计费 token。未知模型或资源不可用时，本地 token 触发不做猜测，仍可按消息数触发；框架也支持同 provider 的可信 usage 元数据触发。

自定义提示词要求保留用户目标、硬性要求与后续纠正、对象 ID/版本、引用与转存路径、待办、失败/未核验状态和未完成审批。摘要模型失败或返回空摘要会中断本轮，原有历史保留，不伪造成功摘要。摘要内容不会作为聊天回复流向页面。

关键状态有两条独立保留路径：

1. 工作台原始用户/助手消息不被摘要覆盖；图内增量 checkpoint 保留原始消息和摘要事件，重启后恢复有效模型历史。
2. `TaskContextBuilder` 每轮重新注入初始用户请求、带明确约束标记的原文候选摘录、待确认操作与状态、授权范围内的附件 ID/版本、Skill 绑定版本、台账和资料档案版本、已有事项状态。原文摘录按时间保留，不能自行把旧要求或纠正解释为执行授权；操作和版本以业务数据库为准。

约束摘录只匹配显式标记（词表与长度上限见 [原生压缩说明](native-compaction.md#每轮硬性要求)），不声称完成了语义识别。未带标记的后续要求仍由摘要提示词保留，完整原文可从工作台历史核对。真实模型是否稳定保留复杂要求，留待获得授权后的质量验收；模拟测试只能证明状态通路和触发机制。

## 统计与对照脚本

`usage.context_management` 只记录数值和 tokenizer 元数据：组别、转存次数、原始/初次精简返回字符数、实际读回字符数、普通与摘要模型调用次数、摘要前后本地历史 token 窗口。摘要开销计入模型总调用次数；若摘要或失败调用未报告用量，整轮相关 token 总量为未知，不用 0 补齐。摘要发生时，未单独观测的缓存总量也为未知。

```sh
cd backend
LANGSMITH_TRACING=false .venv/bin/python scripts/evaluate_runtime_context.py --output ../docs/runtime-context-synthetic.json
```

脚本固定只允许模拟模型，无真实模型模式；不读取 `.env`。所有数据库、状态和转存文件位于临时目录，运行后删除。长页面从仓库 `tests/synthetic_application_site.py` 的合成表单构建，工具读取被替换为内存返回，不发送网页请求。

`evaluation/runtime-context-cases.json` 包含普通聊天、知识库问答、合成表单资料包、合成长页面和八轮长对话。脚本跑 3 组 × 5 项，验证引用匹配、资料包来源、未提交状态、原始历史保留、预期转存/读回和只有 C 触发摘要。失败会返回非零退出状态。

样例结果见 `runtime-context-synthetic.json`：15 组均通过。长页面的共同原始工具响应为 56396 字符，B/C 初次精简返回均为 1225 字符，随后各读回 2116 字符；工具调用从 A 的 1 次变成 B/C 的 2 次。八轮长对话只有 C 发生摘要，共 6 次，样例历史窗口从约 4100 token 缩到约 2100 token。

这些数字证明返回策略和摘要机制工作，不能证明框架更省钱或回答更好。脚本的消息 token 代理计数范围在每行结果注明，A/B 的 SDK 内部历史不可见，不能直接与 C 排名。真实计费 token、缓存命中率及质量分保持 null；CPU 模拟耗时不是 provider 延迟。

后续真实质量验收应分别核对事实是否与合成资料一致、引用是否支持结论、是否编造字段或提交状态、硬性要求与版本是否保留；没有证据的项不能给通过分。真实模型对照仍需用户明确同意后另行运行。

## 验证与阶段边界

```sh
cd backend
LANGSMITH_TRACING=false .venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m pip check
cd ../frontend
PATH=/usr/local/bin:$PATH npm test
PATH=/usr/local/bin:$PATH npm run build
cd ..
git diff --check
```

新增测试覆盖脱敏转存、全文分页读回、大文件、符号链接拒绝、A/B 返回开关与清理、实际图摘要触发和重启、最新资料版本和审批状态、附件隔离、工具消息配对、摘要失败、真实 tokenizer 计数与未知模型行为、A/B/C 独立控制。

最终结果：后端 375 项，370 项通过、5 项跳过；前端 84 项通过；构建通过，保留既有包体积提示；`pip check` 无依赖冲突，`git diff --check` 通过。离线对照 15 组均通过。

以上测试数量与对照数字属于阶段 4 历史记录。当前实现与验收范围见 [双运行时原生压缩](native-compaction.md)。
