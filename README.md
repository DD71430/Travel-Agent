# 智能旅游 Agent

这是一个支持多轮对话与多模态输入的智能出行/旅行 Agent 项目。

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

## 启动方式

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

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

## 下一步可继续升级

- 接入腾讯地图地址解析接口，把文本地址自动转成坐标
- 接入千问多模态接口
- 让图片内容参与意图识别与路线推荐
