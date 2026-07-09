# 智能旅游 Agent

这是一个支持多轮对话与多模态输入的智能出行/旅行 Agent 项目。后端主 Agent 编排统一使用 LangGraph，入口为 `backend/travel_agent/agent/travel_graph.py` 中的 `unified_graph`。

## 当前地图服务

已切换为 **腾讯地图 API**。目前已支持：

- 驾车路线规划
- 步行路线规划
- 骑行路线规划
- 公交路线规划

接口会优先请求腾讯地图真实 WebService，若接口异常则自动回退到本地 fallback 方案，便于项目持续可运行。

## 已具备能力

- 多轮对话
- 历史记忆
- 意图识别
- 出行场景分类
- 路线规划结果结构化输出
- 多模态输入支持（上传图片、文档、PDF、语音）
- 前后端分离
- Docker 支持

## Agent 工作流

当前 `/chat` 与 `/chat/multimodal` 都走 LangGraph `unified_graph`：

1. `ensure_request` 规范化会话 ID。
2. `classify` 判断普通问答、旅行规划或周边推荐。
3. `prepare_travel_request` 将聊天请求转换为旅行规划请求。
4. `build_travel` 调用腾讯地图与旅行规划服务生成行程。
5. `build_nearby` 调用腾讯地图周边 POI 服务。
6. `build_general` 调用 Qwen 兼容 chat completions 完成普通问答。

旧的 `workflow.py`、`planner.py`、`executor.py`、`reflection.py`、`graph.py` 仅作为历史兼容代码保留，不再作为 API 主路径。

## 环境变量配置

项目根目录通过 `.env` 读取配置，提交仓库时请不要提交真实密钥。

### 1. 复制环境变量模板

```bash
cp .env.example .env
```

Windows PowerShell 可以使用：

```powershell
Copy-Item .env.example .env
```

### 2. `.env` 示例

```env
# 千问 / DashScope
QWEN_API_KEY=your-qwen-api-key
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MULTIMODAL_BASE=https://dashscope.aliyuncs.com/api/v1
QWEN_MODEL=qwen3.7-plus
AUDIO_UNDERSTANDING_MODEL=qwen-audio-turbo-latest
ASR_MODEL=Qwen-ASR-Realtime
DASHSCOPE_WORKSPACE_ID=your-dashscope-workspace-id
DASHSCOPE_REGION=cn-beijing
FUN_ASR_SAMPLE_RATE=16000
FUN_ASR_LANGUAGE_HINT=zh

# 腾讯地图
TENCENT_MAPS_KEY=your-tencent-maps-key
TENCENT_MAPS_BASE_URL=https://apis.map.qq.com

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_PREFIX=travel_agent
MEMORY_TTL_SECONDS=604800

# 前端跨域
CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000

# 调试开关
DEBUG=true
RETURN_DEBUG_META=true
MAX_UPLOAD_BYTES=10485760
MAX_EXTRACT_CHARS=4000
FFMPEG_PATH=
```

### 3. 需要配置的关键项

至少需要填写：

- `QWEN_API_KEY`
- `DASHSCOPE_WORKSPACE_ID`
- `TENCENT_MAPS_KEY`

其余参数可先沿用默认值。

### 4. 说明

- `QWEN_API_BASE`：千问兼容接口地址
- `QWEN_MULTIMODAL_BASE`：多模态接口地址
- `QWEN_MODEL`：文本模型名称
- `AUDIO_UNDERSTANDING_MODEL`：音频理解模型名称
- `ASR_MODEL`：实时语音识别模型名称
- `FUN_ASR_SAMPLE_RATE`：语音识别采样率
- `FUN_ASR_LANGUAGE_HINT`：语音识别语言提示
- `TENCENT_MAPS_BASE_URL`：腾讯地图 WebService 地址
- `REDIS_URL`：Redis 连接地址
- `REDIS_PREFIX`：Redis 键前缀
- `MEMORY_TTL_SECONDS`：对话记忆过期时间（秒）
- `CORS_ORIGINS`：允许的前端跨域地址
- `DEBUG`：是否开启调试模式
- `RETURN_DEBUG_META`：是否返回 LangGraph 处理 notes 等调试信息
- `MAX_UPLOAD_BYTES`：单个上传文件大小限制
- `MAX_EXTRACT_CHARS`：文本/PDF/语音提取内容最大字符数
- `FFMPEG_PATH`：本地 ffmpeg 可执行文件路径，可留空使用系统 PATH

`DEBUG=false` 时，接口不会返回语音原始事件、完整地图 payload 等详细调试信息。

## 启动方式

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn travel_agent.main:app --reload --host 0.0.0.0 --port 8000
```

语音识别依赖 ffmpeg。本地运行需要先安装 ffmpeg，或通过 `FFMPEG_PATH` 指向可执行文件；Docker 镜像会自动安装 ffmpeg。

### 前端

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker compose up --build
```

## 测试与质量检查

```bash
py -m compileall backend
py -m pytest backend/tests
cd frontend
npm run typecheck
npm run build
```

## 下一步可继续升级

- 接入腾讯地图地址解析接口，把文本地址自动转成坐标
- 接入千问多模态接口
- 让图片内容参与意图识别与路线推荐
