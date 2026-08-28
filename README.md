# AI Agent Workbench - M1

M1 打通了以下最小链路：

`React Web 页面 -> FastAPI -> Claude Agent SDK -> DeepSeek Anthropic 兼容接口 -> SSE 流式回复`

当前内置 Agent 为 `timesheet_assistant`（工时助理）。前端支持创建会话、发送消息、显示流式回复，并在同一个会话中继续追问。

## 1. 环境要求

- Python 3.12
- Node.js 20 或更高版本
- npm
- 可用的 DeepSeek API Key
- 能够访问 DeepSeek API 服务的网络

## 2. 获取代码

```bash
git clone https://github.com/AI-PROJECT-MANAGEMENT-LAB/ai-agent-workbench-0730.git
cd ai-agent-workbench-0730
git switch function/m1-sdk-web-mvp
```

## 3. 启动后端

### Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS 或 Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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

## 5. 验证 M1

按照 [M1 演示脚本](./docs/demo-scripts/m1-demo-script.md) 完成三个对话样例，重点检查：

1. 页面能选择工时助理。
2. 消息通过 FastAPI 发送给 Claude Agent SDK。
3. 回复以 SSE 流式显示，而不是等待完整结果后一次出现。
4. 同一个页面会话可以连续追问。

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
backend/
  app/main.py                         FastAPI 接口和 SSE 输出
  app/agents.py                       内置 Agent 配置
  app/schemas.py                      API 请求和响应模型
  app/services/claude_runtime.py      Claude Agent SDK 封装
  app/services/conversation_store.py  会话和消息存储
frontend/
  src/App.tsx                         聊天页面和 React 状态
  src/api.ts                          后端请求和 SSE 解析
  src/types.ts                        TypeScript 数据类型
docs/
  demo-scripts/
    m1-demo-script.md                 M1 演示步骤和对话样例
    m2-demo-script.md                 M2 演示、验收和交接步骤
```

会话数据当前保存在后端进程内存中。重启后端后会话会清空，这是 M1 的简化设计，不是生产级持久化方案。
