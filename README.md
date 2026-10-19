# AI Agent Workbench

基于 React、FastAPI 和 Claude Agent SDK 的团队内部 AI 工作台原型，当前进度覆盖 M1–M3：

- 工时助理：模拟日程、草稿、人工确认或取消提交。
- 制度问答助理：通过 stdio MCP 查询本地 Markdown 制度。
- Agent Manifest、Prompt、Skill、工具白名单与审计日志。
- SSE 流式回复、会话切换和 SQLite 消息持久化。
- Docker Compose 开发环境。
- 在页面创建自定义 Agent，连接 HTTP/SSE MCP 服务并选择工具。
- 网页创建、编辑和导入自定义 Skill，绑定到 Agent；模型先查看用途目录，再按需读取正文，支持 Markdown 预览、版本记录和历史回答版本追溯，见 [自定义 Skill](docs/custom-skills.md)。
- 建立本地知识库，上传 Markdown/TXT 文档；Markdown 按标题块分段并重叠一个完整块，可预览来源并测试关键词检索。
- 检索结果按原文位置合并重叠片段，显示候选与去重数量、后端检索耗时；批量评估同步记录逐题耗时。
- 新建或已有 Agent 可绑定知识库，在对话中调用受绑定范围限制的只读检索工具。
- 知识库回答支持可点击引用、原文快照、来源卡片和历史恢复，无匹配时显示依据状态。
- 知识库支持批量检索评估、18 道示例题、自定义 JSON 题集和报告导出。
- 本地 Notes 可通过独立只读 MCP 服务提供给模型，支持分类列表、笔记搜索和原文读取；见 [笔记 MCP 服务](docs/notes-mcp.md)。

对话主链路：

`React Web 页面 -> FastAPI -> Claude Agent SDK -> DeepSeek Anthropic 兼容接口 -> SSE 流式回复`

内置 `timesheet_assistant`（工时助理）和 `policy_qa_assistant`（制度问答助理），也可以通过页面“创建 Agent”添加自定义 Agent。工时和制度数据用于演示，没有连接真实日历、工时或企业审批系统。

## Docker 快速启动（推荐用于换电脑开发）

本机安装并启动 Docker Desktop（Linux 也可以使用 Docker Engine 和 Compose 插件），Compose 至少为 2.30。

```bash
git clone https://github.com/ChengJu1/AI-Agent-workbench.git
cd AI-Agent-workbench
cp backend/.env.example backend/.env
```

私有仓库需要先登录有访问权限的 GitHub 账号。Windows PowerShell 使用 `Copy-Item backend/.env.example backend/.env` 复制模板。

编辑 `backend/.env`，填写自己的模型密钥和接口配置，然后：

```bash
docker compose up --build -d
docker compose ps
```

- 页面：http://localhost:5173
- 健康检查：http://localhost:8000/api/health
- 接口文档：http://localhost:8000/docs

Docker 会安装 Python、Node 和项目依赖，宿主机不需要另建虚拟环境。首次构建需要联网下载镜像和依赖。没有有效密钥时仍可检查页面和健康接口，真实对话需要有效模型配置。

```bash
docker compose logs -f backend frontend
docker compose exec backend python -m unittest discover -s tests -p 'test_*.py' -v
docker compose exec frontend npm test
docker compose exec frontend npm run build
docker compose down
```

普通 `down` 保留数据。`down -v` 会删除卷中的数据库和 SDK 会话，不作为日常停止命令。前端改动自动刷新，后端 Python 改动自动重载；修改内置 Agent JSON、Prompt 或文件 Skill 后执行 `docker compose restart backend`。页面保存的自定义 Skill 和绑定从下一轮对话生效，无需重启。

换电脑时重新克隆代码、配置本机 `.env`，执行相同启动命令。数据库、SDK 会话和密钥不会通过 Git 自动同步。详细实验步骤见 [Docker 开发指南](docs/docker-development.md)。

下面保留不使用 Docker 时的本机启动方法，两种方式请选择一种运行，避免端口冲突。

## 1. 环境要求

- Python 3.11
- Node.js 22
- npm
- 可用的 DeepSeek API Key
- 能够访问 DeepSeek API 服务的网络

## 2. 获取代码

```bash
git clone https://github.com/ChengJu1/AI-Agent-workbench.git
cd AI-Agent-workbench
```

## 3. 启动后端

### Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

### macOS 或 Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

打开 `backend/.env`，将占位值替换为有效密钥：

```dotenv
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=your_deepseek_api_key_here
ANTHROPIC_AUTH_TOKEN=your_deepseek_api_key_here
ANTHROPIC_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
```

不要提交 `backend/.env`。项目只提交不含真实密钥的 `.env.example`。

启动后端：

```bash
uvicorn app.main:app --port 8000
```

看到 `Application startup complete` 后，访问以下地址检查服务：

- 健康检查：http://127.0.0.1:8000/api/health
- API 文档：http://127.0.0.1:8000/docs

健康检查应返回：

```json
{"status":"ok"}
```

## 4. 启动前端

保留后端终端，再打开一个新终端：

```bash
cd frontend
npm ci
npm run dev
```

访问：http://localhost:5173

页面顶部应显示“工时助理”。发送消息后，页面应逐步显示 DeepSeek 模型的回复。

页面中的“创建 Agent”支持填写名称、用途和提示词，连接 MCP 服务、读取并选择工具。创建后立即切换到新 Agent，配置会保存在 SQLite 中。具体连接方式及前后端接口见 [自定义 MCP Agent](docs/custom-mcp-agents.md)。

工具栏“知识库”支持创建知识库、上传文档、预览分段和关键词检索。支持 UTF-8 Markdown/TXT，单文件最大 2 MB。Markdown 按相邻两个标题块分段，重叠一个完整块；无标题文档和 TXT 回退到字符分段。安装更新后的后端依赖并重启后端，会自动升级已有文档索引，保留内容版本和历史引用；详见 [知识库使用说明](docs/knowledge-base.md)。

创建 Agent 时可勾选知识库；已有 Agent 可通过工具栏“绑定知识库”修改。绑定后，Agent 能在对话中调用检索工具，详见 [Agent 知识库绑定](docs/agent-knowledge.md)。

回答中的引用按钮可打开文件版本、行号和原文快照，刷新后仍保留。旧消息不自动补写引用，升级后请新建对话测试；详见 [带引用的知识库问答](docs/knowledge-answers.md)。

在知识库中展开“批量检索评估”，可运行示例题集或导入自己的 JSON 题集，检查目标文档、关键原文和空结果，再导出报告；详见 [检索评估说明](docs/retrieval-evaluation.md)。

## 5. 验证 M1–M3

按照 [M1 演示脚本](./docs/demo-scripts/m1-demo-script.md)、[M2 演示脚本](./docs/demo-scripts/m2-demo-script.md) 和 [M3 演示脚本](./docs/demo-scripts/m3-demo-script.md) 检查：

1. 页面能选择工时助理。
2. 消息通过 FastAPI 发送给 Claude Agent SDK。
3. 回复以 SSE 流式显示，而不是等待完整结果后一次出现。
4. 同一个页面会话可以连续追问。
5. 工时草稿提交前出现确认卡片，确认和取消后的状态正确。
6. 制度助理使用 MCP 工具，回答附带制度来源，审计接口可以查询工具记录。
7. 切换会话后显示对应历史消息。

自动化测试使用临时数据库，部分模型调用使用替身；测试通过不等于已经验证真实模型端到端链路。

本机运行测试时，在已激活后端虚拟环境的终端中执行：

```bash
cd backend
python -m unittest discover -s tests -p 'test_*.py' -v
```

前端在另一个终端中执行：

```bash
cd frontend
npm test
npm run build
```

代码结构、已修复问题和验证边界见 [代码检查与重构记录](docs/review/refactor-review.md)。

## 6. 常见问题

### 前端无法请求后端

确认后端运行在 `http://127.0.0.1:8000`，前端运行在 `http://localhost:5173`。后端 CORS 当前允许该前端地址。

### 页面显示认证或权限错误

确认 `backend/.env` 使用有效的 DeepSeek API Key，并且 `ANTHROPIC_BASE_URL` 为 `https://api.deepseek.com/anthropic`。API 认证错误不代表 React、FastAPI 或 SSE 启动失败。

### Windows 后端无法启动 Claude 子进程

请先使用不带 `--reload` 的命令：

```bash
uvicorn app.main:app --port 8000
```

### 端口被占用

停止占用 8000 或 5173 端口的旧进程，然后重新启动对应服务。

## 7. 项目结构

```text
compose.yaml                         前后端开发容器与持久化卷
backend/
  Dockerfile                         Python、SDK 和后端开发依赖
  agents/                            Agent JSON、Prompt 和 Skill
  app/main.py                        Uvicorn 启动入口
  app/application.py                 应用工厂、启动初始化和异常处理
  app/container.py                   组装数据库、工具和业务服务
  app/config.py                      环境配置与默认路径
  app/api/                           HTTP 接口、SSE 输出与断连清理
  app/models/                        API、Agent 和工具参数模型
  app/services/                      会话、审批、SDK Runtime 与 MCP 审计
  app/storage/                       SQLite 连接、事务、表结构和制度缓存
  app/tools/                         CLI、MCP 适配和 SDK 工具注册
  mcp_servers/policy_server.py        制度 MCP stdio Server
  tools/timesheet_cli.py              模拟工时 CLI
  tests/                             临时数据库、模型替身和 MCP 回归测试
frontend/
  Dockerfile                         Node 开发镜像
  src/App.tsx                        组合聊天页面组件
  src/components/                    消息、输入、会话选择与审批卡片
  src/hooks/useWorkbench.ts          工作台状态和异步交互
  src/api/                           HTTP 请求、错误处理和 SSE 解析
  src/lib/                           消息更新、显示文案与浏览器存储
  src/types.ts                       TypeScript 数据类型
  tests/                             消息状态与 SSE 分块解析测试
docs/
  demo-scripts/
    m1-demo-script.md                 M1 演示步骤和对话样例
    m2-demo-script.md                 M2 演示、验收和交接步骤
    m3-demo-script.md                 M3 MCP 演示步骤
  docker-development.md              Docker 开发与双电脑实验
  review/refactor-review.md           代码检查、重构和验证记录
```

应用会话和消息保存在 SQLite，模型上下文通过 SDK 的 `session_id` / `resume` 续接。Docker 分别持久化数据库目录和 SDK 会话目录；Docker 环境默认使用独立数据库，不会自动导入宿主机已有的聊天记录。

后端在应用启动时初始化数据库。可通过 `WORKBENCH_DATABASE_PATH`、`WORKBENCH_AGENTS_DIRECTORY` 和 `WORKBENCH_CORS_ORIGINS` 覆盖数据库路径、Agent 目录和允许的前端来源；路径默认指向 `backend` 下对应目录，来源列表用英文逗号分隔。
