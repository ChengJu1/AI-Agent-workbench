# Docker 开发与双电脑实验

## 这次 Docker 解决什么

以前换一台电脑，要安装合适的 Python、Node，创建虚拟环境、安装依赖，再分别启动服务。现在这些运行环境由两份 Dockerfile 和 `compose.yaml` 描述。

| 概念 | 在本项目中的含义 |
| --- | --- |
| Dockerfile | 安装运行环境和依赖的配方 |
| 镜像 | 按配方构建好的 Linux 环境与应用文件 |
| 容器 | 使用镜像启动的前端或后端进程 |
| 源码映射 | 本机修改的代码立即出现在容器里 |
| 命名卷 | 容器重建后仍保留的数据库、SDK 会话、前端依赖 |
| Compose | 统一定义并启动两个服务及它们之间的连接 |

Docker 帮助重建环境，Git 帮助同步代码。两者都不会自动把电脑 A 的数据库、密钥或编辑器配置同步到电脑 B。

## 容器如何连接

```text
浏览器 http://localhost:5173
  → 前端容器中的 Vite
  → /api 代理到 http://backend:8000
  → 后端 FastAPI
  → Claude Agent SDK
      → SDK 工时工具 → CLI 子进程
      → 制度 MCP stdio 子进程
```

`backend` 是 Compose 网络中的服务名称。浏览器不能直接解析这个名称，所以由前端开发服务器代理请求。无需把容器 IP 写进代码。

镜像中的服务监听 `0.0.0.0`，宿主机发布端口绑定在 `127.0.0.1`，供本机浏览器测试。

## 第一次启动

1. 安装并启动 Docker Desktop，确认 `docker info` 和 `docker compose version` 可用。
2. 克隆私有仓库 `https://github.com/ChengJu1/AI-Agent-workbench.git`。
3. 将 `backend/.env.example` 复制成 `backend/.env`，填写自己的模型配置。
4. 在项目根目录执行：

```bash
docker compose up --build -d
docker compose ps
```

第一次构建需要下载 Python / Node 基础镜像和项目依赖；后续构建可以复用缓存。没有有效密钥时，仍可检查页面、Agent 列表、健康接口和接口文档。

Compose 至少需要 2.30，因为配置使用可选的 `env_file` 和 `format: raw`，避免密钥中的特殊字符被 Compose 插值。`.env` 不进入 Git，也不会通过 Docker 构建上下文进入镜像。

## 双电脑实验

### 电脑 A：修改并同步代码

启动后打开 `http://localhost:5173`，修改页面中的一句文字并保存，观察自动刷新。

确认改动后，将明确的文件提交到个人仓库：

```bash
git add frontend/src/App.tsx
git commit -m "chore: verify Docker development workflow"
git push
```

如果还在原来的实习目录中开发，该目录保留原 `origin`，个人仓库的远程名为 `workbench`。上传当前进度使用：

```bash
git push workbench HEAD:main
```

这里不需要向原来的团队仓库推送，也不需要强制推送。

### 电脑 B：重建同样的开发方式

准备 Docker 和 Git，然后：

```bash
git clone https://github.com/ChengJu1/AI-Agent-workbench.git
cd AI-Agent-workbench
```

重新创建本机的 `backend/.env`，再执行：

```bash
docker compose up --build -d
```

检查页面上是否出现电脑 A 提交的修改。这个过程不需要把 A 的 `.venv` 或 `node_modules` 复制过来；容器会为 B 的系统架构重新安装依赖。

同一份配置可以用于 Apple Silicon、常见 Intel/AMD 电脑；镜像按各自架构构建。当前没有跨两台实体电脑实测，另一台机器的网络、CPU 架构和 Docker 安装仍需现场验证。

## 源码、依赖与配置分别怎么更新

| 修改内容 | 操作 |
| --- | --- |
| React 代码或 CSS | 保存，Vite 自动更新 |
| 后端 Python | 保存，Uvicorn 自动重载 |
| Agent JSON / Prompt / Skill | `docker compose restart backend`，重新加载 Registry |
| Python requirements | `docker compose up --build -d backend` |
| 前端 package / lock 文件 | 先运行下方依赖同步命令，再构建前端 |
| `backend/.env` | `docker compose up -d --force-recreate backend`，重新注入环境变量 |

更新前端依赖卷：

```bash
docker compose run --rm --no-deps frontend npm ci
docker compose up --build -d frontend
```

宿主机的 `node_modules` 与容器中的 Linux 依赖分开，避免把 macOS 或 Windows 的原生二进制加载进 Linux。

## 数据存在哪里

- `backend_data`：容器内 `/workspace/backend/data`，保存 Docker 环境自己的 SQLite 数据。
- `claude_sessions`：容器内 `/home/appuser/.claude`，保存 SDK / CLI 会话文件。
- `frontend_node_modules`：容器内 `/workspace/frontend/node_modules`，保存 Linux 前端依赖。

模拟日程和制度文件额外从仓库映射进来，方便更新演示数据。宿主机已有的 `backend/data/workbench.db` 不会复制进镜像；Docker 环境从自己的数据库开始，不会自动导入旧聊天记录。

```bash
docker compose down
docker compose up -d
```

上述操作会重建容器并保留命名卷。不要为了日常重启使用 `down -v`，它会删除这些卷中的数据。卷只在当前电脑上，不是云端同步或自动备份。

## 检查和排错

```bash
docker compose ps
docker compose logs --tail=100 backend frontend
docker compose exec backend python -m unittest discover -s tests -p 'test_*.py' -v
docker compose exec frontend npm run build
```

真实模型测试会使用 API 配额，由用户在页面发送消息执行。健康检查、单元测试和前端构建不等于已经完成真实模型联调。

如果 Docker Hub 的认证地址连接超时，可以尝试 AWS Public ECR 上的 Docker 官方镜像副本，再为本机镜像添加 Dockerfile 使用的标签：

```bash
docker pull public.ecr.aws/docker/library/node:22-bookworm-slim
docker tag public.ecr.aws/docker/library/node:22-bookworm-slim node:22-bookworm-slim
docker compose build frontend
```

这只增加本机镜像标签，不修改系统网络或 Docker 全局镜像源。其他电脑如果能正常连接 Docker Hub，不需要这一步。

如果 8000 / 5173 被其他本机进程占用，先停止旧的本机开发服务，或覆盖端口：

```bash
# macOS / Linux
BACKEND_PORT=8001 FRONTEND_PORT=5174 docker compose up -d
```

```powershell
# Windows PowerShell
$env:BACKEND_PORT="8001"
$env:FRONTEND_PORT="5174"
docker compose up -d
```

这时页面访问 `http://localhost:5174`，健康接口访问 `http://localhost:8001/api/health`。前端代理仍使用容器内部的 `backend:8000`。

## 当前边界

这是带源码映射、Vite 和 Uvicorn reload 的开发环境。面向公网部署还需要生产构建、访问控制、HTTPS、密钥管理和备份等配置。

镜像固定 Python / Node 主版本，后端固定直接依赖版本，前端使用 lock 文件安装。基础镜像仍可能获得更新，Python 的部分间接依赖也未完全锁定，因此不能承诺每次构建产生逐字节相同的镜像。

## 本次验证记录

- 环境：Apple Silicon 上的 Docker Desktop，Linux ARM64 容器。
- 后端镜像构建成功，现有 M2/M3 自动化测试 16/16 通过。
- SDK 附带的 Linux Claude CLI 能以普通用户运行；没有调用真实模型。
- 独立 MCP stdio 子进程能完成 `tools/list` 和 `search_policy`。
- 前端镜像构建及 `npm run build` 成功。
- Compose 启动成功，页面、通过前端代理的健康接口和 Agent 列表均返回 HTTP 200。
- 现有前端锁文件的 `npm audit` 报告 `source-map-js` 有 1 项 high 告警；此次没有扩展范围升级原项目依赖，后续可单独处理。
- 第二台实体电脑尚未实测；真实模型对话由用户使用自己的密钥测试。

参考：[Docker Python 开发指南](https://docs.docker.com/guides/python/)、[Compose 环境变量](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)、[Docker 数据卷](https://docs.docker.com/engine/storage/volumes/)。
