# 正常浏览器方案：独立验证

用 Microsoft `@playwright/mcp@0.0.83` 替换实验中的自建页面网络代理，先验证浏览器路线。**不是正式平台迁移，也不是自动投递功能。**

## 启动

从仓库根目录运行（需要 Node.js 18+、已安装的 Google Chrome、后端现有虚拟环境）：

```sh
npm install --prefix backend/data/platform-validation/native-browser-mcp --ignore-scripts --no-audit --no-fund --save-exact @playwright/mcp@0.0.83
backend/.venv/bin/python backend/experiments/native_browser/server.py
```

打开 <http://127.0.0.1:8088/>。服务仅监听回环地址，生产工作台的 5173/8000 和现有浏览器不变。不要使用 `--reload` 或部署到公网。

## 运行方式与边界

- Python MCP SDK 通过 stdio 调用固定版本的官方 MCP，浏览器为已安装的普通 Chrome。
- 专用持久配置位于 `backend/data/platform-validation/native-browser-mcp/profile/`，与个人 Chrome 及旧工作台会话分离；新建目录权限 0700。关闭实验窗口、重启实验服务不会主动清除它，网站自身仍可能要求重新登录。
- 浏览器按正常方式联网，不使用 `BrowserService._route_request`、后端 HTTP 转发、逐资源授权、Cookie 剥离或静态资源补丁；没有关闭浏览器沙箱、证书校验或浏览器自身的同源限制。
- 网站正常运行会产生自身的网络请求，包含跨域依赖和初始化 POST；**不能把这个实验理解为“浏览器不会写入”的强保证**。目前仅做人工在场的方案验证，正式多用户/服务器部署必须另外实现执行环境和网络出口隔离。
- HTTP 页面只开放固定公开岗位/登录页/合成页导航，以及 snapshot、脱敏请求列表、手动截图、关闭窗口。没有任意 URL、工具名或参数代理，不开放 JavaScript 执行、点击、填写、上传、提交、存储导出工具；关闭了页面注册的 WebMCP 工具发现。
- 本地操作接口要求随机页面凭证、可信 Host 和同源 Origin；无 CORS 放行。不是面向不可信本机进程的安全隔离。
- 不轮询画面、DOM 或诊断，不自动刷新/重试。登录由用户在新 Chrome 完成，返回后主动读取页面。勾选“正在登录”只是本地页面暂停开关，不是浏览器网络权限。
- 正文快照通过显式 snapshot 返回当前本地页面，不写入工作台数据库；自动导航快照关闭。截图与官方工具错误附件可能存入专用 output 目录，请将整个专用目录视作可能包含账号状态的本地敏感数据。它已被仓库现有 `.gitignore` 忽略，不提交或同步。
- 请求诊断仅保留 method、host、path、status 和错误代码，不显示 query、Cookie、请求头或正文。不能从网络状态推断业务已投递。

## 验收步骤

1. 点击“验证合成表单”，然后“读取当前页面”：应看见 POST 数据查询与跨域脚本初始化成功、姓名输入框和岗位下拉框。
2. 查看请求结果：`POST /fixture/options` 和跨域脚本应为 200，合成提交计数为 0。
3. 关闭专用窗口，再打开合成表单：访问次数应增加，证明专用配置保留；这不是对真实网站登录有效期的保证。
4. 打开真实岗位与登录页，确认正常渲染；请用户本人登录并进入填写页，之后读取真实字段。只见登录页或岗位页不算真实表单验收通过。
5. 在真实表单检查 `/api/common/Datasource` 的结果、字段是否可用，再决定正式迁移。不要上传或提交简历。

单元验证：

```sh
cd backend
.venv/bin/python -m unittest discover -s experiments/native_browser -p 'test_*.py'
```

覆盖命令边界、跨站操控防护和诊断去敏。实际网页验收必须通过界面完成，不能以这些测试代替。

## 迁移决策

2026-10-20 实际验收：用户本人在新窗口完成登录并进入真实填写页，随后官方 snapshot 读取到个人信息、教育经历、项目经历等输入项及“预览并提交”按钮；请求元数据中 `CheckJobAd`、`FormWithFillData`、`Datasource` 均为 200。未填写、上传、暂存或提交。表单中仍有资源错误（例如 IMLib 连接关闭），本轮只确认表单渲染与结构化读取，不保证所有交互或其他网站。

验证支持将浏览器后端抽为 provider：现有平台保留文件版本、确认清单、台账和跟踪；官方浏览器工具由平台包装后按能力暴露，不能把官方 MCP 的全工具集直接放行给模型。授权操作需绑定当前页面/目标/文件版本，并处理导航及页面变化使旧批准失效。先完成本机 provider、审批动作适配和会话生命周期，再处理多用户/服务器隔离；现有正式工作台尚未切换。

参考：[官方 MCP](https://github.com/microsoft/playwright-mcp)、[持久化与已有浏览器连接](https://github.com/microsoft/playwright-mcp#user-profile)。
