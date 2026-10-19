# 平台构建助手与生成能力包

入口是侧栏「创建 Agent」。默认打开平台维护的构建助手；原来的 MCP、Skill、知识库配置保留在「高级手动配置」。

## 使用流程

1. 描述输入、处理规则、输出和边界情况。当前支持传入文本、CSV、JSON 的计算、整理、校验与转换。
2. 构建助手缺少规则时会提问。用户补充要求后继续生成。
3. 模型现场编写 Python 方法、输入输出 Schema 和合成测试。平台校验代码与契约，并在独立环境执行测试；失败时把实际结果交回模型修正一次。
4. 页面展示方法、工作规则和实际测试结果。只有全部通过，才出现「创建并使用」。样例通过代表这些样例成立，不代表业务正确性已被完全证明；创建前需核对规则。
5. 发布原子保存能力包和 Agent，立即切换到新 Agent。侧栏可自由切换原有 Agent。
6. 再次打开创建入口，可从「构建记录」查看、补充未发布方案，或选择基于已发布能力创建新版本。v2 创建新 Agent，旧 Agent 继续固定使用 v1。

内置示例「按类别汇总订单」使用合成数据，不读取 Notes、项目源码或知识库原文。生成阶段只发送这次构建对话、上一版方案和测试反馈给当前配置的模型。

## 架构与维护边界

```mermaid
flowchart LR
    U[描述需求] --> B[平台构建助手]
    B --> P[生成代码与接口契约]
    P --> T[独立执行实际测试]
    T --> R[用户审阅并创建]
    R --> V[不可变能力包版本]
    R --> A[用户 Agent 固定绑定版本]
    A --> M[此能力包专属 MCP stdio 进程]
    M --> S[独立方法执行环境]
```

- `agent_builds` 保存服务端草稿、对话、状态、修订号、测试报告与发布结果。关闭窗口不会取消正在运行的任务；记录保留后可重新打开。
- `capability_packages` 保存不可变版本，包含代码、契约、测试及 SHA-256。调用前重新检查版本哈希和 Agent 绑定。
- 每个 Agent 的每个能力包由独立 MCP stdio 实例提供方法。共用可信加载器，但不会把生成业务代码集中写进平台的单个 MCP 服务。
- SDK 只得到已绑定版本的方法白名单。生成方法调用进入现有 MCP 审计流程。
- 新版本重新生成并测试；旧版本不覆盖。并行基于同一版本发布时，后提交者需基于最新版本重新构建。
- 发布使用同一 SQLite 事务，避免只保存能力包或重复创建 Agent；重复发布返回同一个 Agent。
- 构建助手自身没有文件、Shell 或 MCP 工具。此版本实现创建与切换，没有实现主 Agent 自动委派任务给其他 Agent。

## 方法运行环境

`python-stdlib-v1`：每个方法定义 `run(arguments)`，接收 JSON 对象并返回 JSON 对象。支持标准库 json、csv、math、statistics、datetime、decimal、re、collections、itertools、functools、string、unicodedata。没有自定义依赖、文件/网络/数据库连接和凭据注入。

代码校验是辅助限制，操作系统隔离才是执行边界。环境不可用时不回退到后端直接执行。

- macOS：系统 `sandbox-exec` 默认拒绝访问，仅允许读取解释器、标准系统库和可信 worker；不能写文件或连接网络。净化环境变量；CPU 限额 2/3 秒，父进程最多等待 7 秒，并采样 RSS 超过 256 MiB 时停止。RSS 是采样保护，不是容器级硬内存隔离。
- Linux：需要可用 Docker 和预先准备好的官方 `python:3.11-slim` 镜像。容器无宿主挂载、无网络、根文件系统只读、无 capabilities，以非 root 用户执行，内存限制 256 MiB；worker 再设置 CPU/内存/文件描述符限制。当前开发机已验证 macOS 路径，Linux Docker 路径需在部署机验收。
- 每次输入连同代码最多 160,000 字节，输出最多 64 KiB。单包最多 6 个方法，每个方法 2–6 个合成测试；这些是生成/执行成本边界，不影响已实现的 Skill 数量规则。
- Schema 只允许基础类型及属性、数组、枚举、数值与长度约束；不允许外部引用、正则或组合表达式，避免后端验证器读取外部资源。

此功能面向现有本地个人工作区。对外多用户部署还需要账号、草稿/包/Agent 的所有权校验、配额与持久化任务队列，不能直接当作公网代码运行服务。

## API

| 接口 | 用途 |
| --- | --- |
| `GET /api/agent-builds/runtime` | 实际探测执行环境 |
| `GET /api/agent-builds/packages` | 已发布能力包最新版本摘要 |
| `GET /api/agent-builds` | 最近 30 条构建摘要 |
| `POST /api/agent-builds` | 使用客户端 UUID 幂等创建构建 |
| `GET /api/agent-builds/{id}` | 获取进度、对话、方案和报告 |
| `POST /api/agent-builds/{id}/messages` | 携带 expected_revision 补充需求 |
| `POST /api/agent-builds/{id}/publish` | 仅发布已通过测试且哈希匹配的方案 |

构建使用当前后端模型配置，每次模型生成限时 120 秒，最多生成两次；每轮方法测试设 40 秒预算，正在执行的单次方法仍受 7 秒超时约束。任务由当前后端进程运行；服务异常中断后超过 6 分钟的旧任务标记为可重试，过期任务不能覆盖新修订。这不是持久化分布式任务队列。

## 验证

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -q
# 在宿主环境额外验证实际隔离与 stdio MCP（嵌套工具沙箱会阻止 sandbox-exec 启动）
WORKBENCH_RUN_SANDBOX_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_agent_builder.py -q
cd ../frontend
npm test
npm run build
```

测试覆盖真实测试失败拦截、澄清和修订、发布幂等、事务回滚、版本固定与并发冲突、哈希/绑定校验、危险代码/Schema 拒绝，以及实际 stdio MCP 调用、文件读写与网络拒绝、循环终止及凭据不继承。
