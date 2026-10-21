# 阶段 3：接入共享工具

Deep Agents 通过 `RuntimeTools` 组装本轮授权工具；`to_langchain` 和 Claude 的 MCP 适配器调用同一套 `ToolDefinition` 与业务服务。容器把 Claude 已有的平台、工时、知识库、Skill 和 MCP 配置服务共享给 Deep Agents，不另建执行、审计或审批策略。

## 行为与边界

- 平台能力按 Agent 授权注册，包含附件、浏览器、台账、资料档案和资料包；共享处理层继续核对实时授权、会话归属和版本。资料包、台账仍按原有规则更新本地记录；浏览器写操作、文件更新、工时提交继续创建 `pending_actions`，只有现有 `ApprovalService` 能执行确认后的动作。
- Skill 使用数据库绑定版本与每轮 `SkillLoads` 预算，模型通过 `search_skills`、`load_skill` 按需读取。预算不足返回错误，不截断规则；没有 Deep Agents SkillsMiddleware。
- 外部 MCP 使用 `langchain-mcp-adapters` 官方转换器。`ExternalToolServer` 仍负责配置中的动作白名单、参数验证、唯一连接生命周期、审计和笔记依据捕获。上游隐藏的工具不会暴露给模型；失败内容沿用安全错误文本。
- 内部工具经 LangChain 图调用时返回标准 MCP 内容块及准确的 ToolMessage 错误状态，避免把失败业务结果包装成成功。直接调用适配器仍可得到原有响应字典。
- 两个运行时统一生成 `tool_started` / `tool_finished`，只包含工具名、调用 ID 和成功标志。状态事件不含参数、工具原文和个人资料。引用和 Skill 事件由共享业务执行结果产生，无需解析某个 SDK 的消息类型。
- 模型在工具调用后失败，仍保留已经创建的审批和引用并发送对应事件；模型不能因失败绕过确认。默认 Deep Agents 开关仍为 false；未启用自动摘要、自动转存、子 Agent 或命令执行。

## 模拟验收

`test_runtime_tool_parity.py` 在相同合成输入下，实际执行 Claude MCP 循环与 Deep Agents 图，比较完整事件类型序列、工具状态字段，并核对持久化结果。用量和随机审批/引用 ID 按各自字段校验，不要求相等。

覆盖工时及浏览器审批、模型后续失败、知识库与外部笔记引用、工具失败的模型错误状态、固定 Skill 旧版本、同一会话每轮预算重置、资料档案/台账读取和资料包生成。`test_deep_agents.py` 额外验证未经授权的平台动作不注册也不执行；适配器和外部 MCP 测试覆盖实时撤权、白名单、参数错误、审计唯一性与连接关闭。现有合成页面回归继续覆盖表单读取、资料包和审批流程。

全部模型为确定性模拟模型，数据库和资料为临时合成数据；没有调用真实模型或真实招聘网站。前端选择器、上下文压缩和真实模型对照分别留到后续阶段。

验收命令与结果：

```sh
cd backend
LANGSMITH_TRACING=false .venv/bin/python -m unittest discover -s tests -q
# 364 项，跳过 5 项，其余通过。
.venv/bin/python -m pip check
# No broken requirements found.
cd ../frontend
PATH=/usr/local/bin:$PATH npm test
# 84 项通过。
PATH=/usr/local/bin:$PATH npm run build
# 通过，保留既有包体积提示。
cd ..
git diff --check
# 通过。
```

没有范围偏离。适配层补充了标准 MCP 错误标志和统一状态事件，因此旧测试需要允许新增状态事件，同时保留审批、引用、Skill 与最终结果的原有顺序。阶段 2、3 均尚未提交；下一步为阶段 4 的上下文管理与模拟对照，等待用户确认后开始。
