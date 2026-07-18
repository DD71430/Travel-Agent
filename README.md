# 智能旅游规划 Agent

这是一个基于 **FastAPI + LangGraph + React + TypeScript** 的智能旅游规划工作台。项目支持通过中间聊天框输入自然语言需求，自动完成旅行意图识别、交通方式解析、腾讯地图路线规划、实时天气融合、每日行程生成、周边推荐、多轮会话记忆和多模态文件输入。

当前版本已移除旧的左侧“行程偏好”表单，旅行规划、天气查询和周边推荐都统一从聊天入口发起。

## 核心能力

- **自然语言旅行规划**：从聊天内容中解析出发地、目的地、天数、交通方式、途经城市和旅行偏好等信息。
- **天气融入行程**：调用腾讯天气能力获取多日天气，并把降雨、高温、防晒、防滑、室内优先等策略直接融入每日景点和时间安排。
- **交通方式识别**：支持自驾、公交/高铁/动车、步行、骑行等出行方式，并按交通工具估算跨城和市内转场时间。
- **腾讯地图路线能力**：使用腾讯地图 WebService 进行地理编码、路线规划、距离和耗时估算。
- **周边推荐**：支持围绕景点或城市查询酒店、餐饮、景点等周边候选。
- **独立天气查询**：可直接询问“杭州未来三天天气怎么样”，前端会显示天气接口诊断和每日天气卡片。
- **Redis 会话记忆**：支持多轮对话、历史记录、长期偏好沉淀；Redis 不可用时自动回退到内存模式。
- **多模态输入**：支持上传文本、PDF、Word 文档和语音文件，后端会抽取或转写内容并参与对话；图片当前仅接收，不做内容识别。
- **前后端分离**：后端提供 FastAPI 接口，前端使用 Vite + React + TypeScript。
- **Docker 支持**：可通过 docker compose 启动后端、前端和 Redis。

## 当前前端交互

前端主界面为三栏工作台：

- 左侧：新建会话、快捷指令、历史记录、Redis/记忆状态。
- 中间：唯一聊天输入区，旅行规划、天气查询、周边推荐都从这里提交。
- 右侧：结果工作区，展示总览、每日行程、天气与装备、调试信息。

旅行规划返回后，中间聊天区只显示简短确认，完整行程在右侧结果区展示，避免重复刷屏。

## 后端 Agent 工作流

`/chat` 与 `/chat/multimodal` 都走 LangGraph 统一编排，入口位于：

```text
backend/travel_agent/agent/travel_graph.py
```

主要流程：

1. `ensure_request`：规范化请求与会话 ID。
2. `classify`：识别普通问答、旅行规划、周边推荐或天气查询。
3. `prepare_travel_request`：从聊天内容提取旅行规划参数。
4. `build_travel`：调用腾讯地图、天气、交通和规划服务生成结构化行程。
5. `build_nearby`：生成周边 POI 推荐。
6. `build_weather_query`：直接返回天气接口诊断和多日天气结果。
7. `build_general`：调用 Qwen 兼容 Chat Completions 完成普通问答。

旧的实验性 `workflow.py`、`planner.py`、`executor.py`、`reflection.py`、`graph.py` 仅作为历史兼容代码保留，不再作为 API 主路径。

## 技术栈

### 后端

- FastAPI
- LangGraph
- Pydantic v2
- httpx
- Redis
- DashScope / Qwen 兼容接口
- Tencent Maps WebService
- pypdf / python-docx / ffmpeg-python / moviepy

### 前端

- React 18
- TypeScript
- Vite
- 原生 CSS 响应式布局

## 环境变量

项目根目录通过 `.env` 读取配置。请复制模板后填写真实密钥，不要提交 `.env`。

```powershell
Copy-Item .env.example .env
```

Linux / macOS：

```bash
cp .env.example .env
```

关键配置：

```env
# Qwen / DashScope
QWEN_API_KEY=your-qwen-api-key
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MULTIMODAL_BASE=https://dashscope.aliyuncs.com/api/v1
QWEN_MODEL=qwen3.7-plus
AUDIO_UNDERSTANDING_MODEL=qwen-audio-turbo-latest
ASR_MODEL=Qwen-ASR-Realtime
DASHSCOPE_WORKSPACE_ID=your-dashscope-workspace-id
DASHSCOPE_REGION=cn-beijing

# Tencent Maps
TENCENT_MAPS_KEY=your-tencent-maps-key
TENCENT_MAPS_BASE_URL=https://apis.map.qq.com

# Redis memory
REDIS_URL=redis://localhost:6379/0
REDIS_PREFIX=travel_agent
MEMORY_TTL_SECONDS=604800

# Frontend CORS
CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000

# Debug
DEBUG=true
RETURN_DEBUG_META=true
MAX_UPLOAD_BYTES=10485760
MAX_EXTRACT_CHARS=4000
FFMPEG_PATH=
```

至少需要填写：

- `QWEN_API_KEY`
- `DASHSCOPE_WORKSPACE_ID`
- `TENCENT_MAPS_KEY`

Redis 可选。未启动 Redis 时，系统会使用内存 fallback，但历史记录不会像 Redis 一样长期保存。

## 本地启动

### 1. 启动后端

```powershell
cd "D:/PycharmProjects/AI Learn/Agent"
py -m venv agent_env
.\agent_env\Scripts\Activate.ps1
pip install -r backend/requirements.txt
cd backend
uvicorn travel_agent.main:app --reload --host 0.0.0.0 --port 8000
```

语音识别依赖 ffmpeg。本地运行需要先安装 ffmpeg，或通过 `FFMPEG_PATH` 指向可执行文件。

### 2. 启动前端

```powershell
cd "D:/PycharmProjects/AI Learn/Agent/frontend"
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

### 3. 可选：启动 Redis

如果本机已有 Redis：

```powershell
redis-server
```

也可以使用 Docker 启动完整服务。

## Docker 启动

日常开发推荐直接使用 Compose 默认文件。`docker-compose.override.yml` 会自动启用热更新：

```powershell
docker compose up --build
```

默认访问地址：

- 前端工作台：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- Redis：`127.0.0.1:6379`

开发模式会把本地 `backend/` 和 `frontend/` 挂载进容器：后端使用 `uvicorn --reload`，前端使用 Vite dev server。保存代码后容器内会自动更新，不需要每次重建镜像。
如果修改了 `requirements.txt`、`package.json`、`package-lock.json` 或 Dockerfile，仍需重新运行 `docker compose up --build` 让依赖和镜像层更新。

如需只验证生产式镜像，不加载开发 override：

```powershell
docker compose -f docker-compose.yml up --build
```

Docker 会启动项目所需服务。生产密钥仍需通过环境变量或 `.env` 提供，不要提交真实密钥。

## 常用接口

- `GET /health`：健康检查。
- `POST /chat`：纯文本聊天入口。
- `POST /chat/multimodal`：聊天 + 文件上传入口。
- `GET /chat/history/{conversation_id}`：读取指定会话历史。
- `POST /plan`：历史兼容接口，前端当前不再主动调用。

## 测试与质量检查

后端：

```powershell
cd "D:/PycharmProjects/AI Learn/Agent"
py -m pytest backend/tests
py -m ruff check backend/travel_agent backend/tests
```

前端：

```powershell
cd "D:/PycharmProjects/AI Learn/Agent/frontend"
npm run typecheck
npm run test --if-present
npm run build
```

## 目录结构

```text
Agent/
├── backend/
│   ├── travel_agent/
│   │   ├── agent/              # LangGraph 编排
│   │   ├── api/                # FastAPI 路由
│   │   ├── memory/             # Redis/内存会话记忆
│   │   ├── models/             # Pydantic 模型
│   │   └── services/           # 天气、路线、规划、周边、意图等服务
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── SidebarPanel.tsx
│   │   ├── chatUi.ts
│   │   ├── planDisplay.ts
│   │   ├── weatherDisplay.ts
│   │   └── styles.css
│   └── tests/
├── docker-compose.yml
├── .env.example
└── README.md
```

## 关于 `tencentmap-jsapi-gl-skill`

仓库中包含 `tencentmap-jsapi-gl-skill` 引用，它是腾讯地图 JSAPI GL 的 AI Skill 文档资料包，用于辅助后续开发地图可视化页面，例如地图初始化、标记点、路线绘制和可视化图层。

当前 Agent 的天气查询、路线规划和后端服务不依赖它运行；它主要是开发参考资料。

## 注意事项

- 不要提交 `.env` 或任何真实 API Key。
- 腾讯地图天气或路线接口异常时，后端会返回 fallback 数据，前端会显示“天气待确认”或对应诊断状态。
- Redis 未启动时仍可使用 Agent，但历史记录和长期记忆能力会受限。
- 前端旅行规划完全依赖聊天输入解析，旧的表单字段不会再参与请求。
- 天气结果按 `day + city` 匹配每日行程，避免把杭州、徐州等不同城市天气串用。

## 后续可扩展方向

- 在右侧结果区加入腾讯地图路线可视化。
- 增加景点开放时间、门票和预约状态校验。
- 将住宿、餐饮、景点候选接入更细粒度评分。
- 增强移动端历史记录抽屉和结果分享能力。
