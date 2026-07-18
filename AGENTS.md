# Codex Project Guide

本项目是一个智能旅游规划 Agent 工作台，后端使用 FastAPI + LangGraph + Pydantic，前端使用 React + TypeScript + Vite + 原生 CSS。Codex 在本仓库工作时优先保持现有架构和用户体验，不做无关重写。

## Project Map

- 后端主入口：`backend/travel_agent/main.py`
- API 路由：`backend/travel_agent/api/`
- 当前 Agent 主编排：`backend/travel_agent/agent/travel_graph.py`
- 旅行规划服务：`backend/travel_agent/services/travel_planner.py`
- 天气、周边、上传、记忆等能力：`backend/travel_agent/services/`
- 腾讯地图 WebService 客户端：`backend/travel_agent/tools/tencent_webservice_client.py`
- 前端主入口：`frontend/src/App.tsx`
- 前端辅助渲染/工具：`frontend/src/chatUi.ts`、`frontend/src/planDisplay.ts`、`frontend/src/weatherDisplay.ts`
- 前端样式：`frontend/src/styles.css`
- 腾讯地图 JSAPI GL 本地参考 skill：`tencentmap-jsapi-gl-skill/tencentmap-jsapi-gl-skill/`

旧的 `backend/travel_agent/agent/workflow.py`、`planner.py`、`executor.py`、`reflection.py`、`graph.py` 主要是历史兼容路径。除非任务明确要求兼容旧路径，否则不要把新功能接到旧实验流程里。

## Working Rules

- 先读相关代码和测试，再改代码。不要根据文件名猜行为。
- 当前仓库可能有用户未提交改动。不要回滚、格式化或整理与任务无关的文件。
- 不要提交、打印或复制 `.env` 中的密钥。新增配置时同步更新 `.env.example` 和 README 说明。
- 保持改动小而可验证。优先修改已有服务、模型和 helper，不为单一需求新建大框架。
- 对外部服务失败要诚实展示降级原因，尤其是腾讯地图、天气、Redis、Qwen/DashScope、语音识别。
- 新增行为必须有测试；修 bug 优先先写能复现问题的测试。

## Backend Rules

- FastAPI 响应应继续保持统一字段：`conversation_id`、`answer_type`、`final_answer`、`data`、`travel_request`、`upload_context`、`meta`、`error`。
- LangGraph 主路径应从 `travel_graph.py` 扩展。新增节点要保证输入/输出写入 `UnifiedAgentState`，并在 `processing_notes` 中留下可调试标记。
- 旅行规划结构优先通过 `TravelPlanRequest`、`TravelPlanResponse` 和相关 Pydantic 模型表达，不要把匿名 dict 扩散到 API 边界。
- 同步外部 I/O 放在线程中或集中在服务层处理。不要在 async 路由里直接加入长时间同步请求。
- 保持 fallback 可解释：当路线、天气或 POI 使用 fallback 时，`data_source`、`fallback_reason`、`request_debug` 应能让前端和测试识别真实数据来源。
- 文件上传只处理允许的文件类型和大小。新增文件类型时同步覆盖成功、失败、超限和空内容测试。
- Redis 不可用时必须继续 fallback 到内存模式，且 API 响应里保留 `meta.memory`。

## Frontend Rules

- 前端是工作台，不是营销页。第一屏应保持三栏或移动端对话/结果切换的高效任务界面。
- 优先复用 CSS 变量和现有类名体系。新增颜色先放到 `:root`，避免散落硬编码色值。
- 保持卡片半径在 8px 或以下，避免卡片套卡片。页面区块应是工作区/面板，重复条目、模态、具体工具才用卡片。
- 不要继续把复杂功能堆进 `App.tsx`。新增大块 UI 时拆成面板组件、展示组件或纯 helper，并为纯 helper 增加测试。
- 结果展示要区分真实数据和 fallback 数据。天气、路线、调试来源不要只靠文案暗示。
- 移动端必须检查 `max-width: 799px` 和 `max-width: 440px` 两档，确保按钮文字、长城市名、长摘要不会溢出或遮挡。
- 当前项目未安装 UI 库。不要为了单个按钮引入大型组件库；如确实需要图标库，优先小范围使用 `lucide-react` 并保持按钮有 `aria-label`/`title`。

## Figma / Design Rules

- 当前推荐配合使用这些 Figma 插件技能：
  - `figma:figma-use`：需要通过 Figma Plugin API 读取/写入文件、检查变量、组件、auto-layout 或节点结构时使用。任何 `use_figma` 调用前必须先加载该技能。
  - `figma:figma-code-connect`：需要把 Figma 组件映射到 React 组件、创建或维护 `.figma.ts` Code Connect 模板时使用。
  - `figma:figma-generate-library`：需要把项目颜色、字体、按钮、输入框、卡片等沉淀为 Figma 组件库或变量库时使用。
  - `figma:figma-generate-design`：需要把当前网页/代码页面同步或生成到 Figma 中，形成可编辑页面稿时使用。
- 若用户提供 Figma 链接或 frame，先提取设计上下文、截图、颜色、间距、字体和组件状态，再改代码。
- 把 Figma 视觉语言映射到现有工作台：左侧会话/快捷指令、中间聊天、右侧路线/天气结果。不要照搬与旅游规划任务无关的营销布局。
- Figma 改版优先沉淀为 CSS 变量、布局规则和可复用组件，而不是一次性大段样式。
- 视觉验收至少覆盖桌面和移动端截图。检查文本是否溢出、面板是否可滚动、结果卡片是否遮挡。
- 涉及腾讯地图可视化时，优先参考本仓库的 `tencentmap-jsapi-gl-skill` 文档和 demo，不要凭记忆编造 JSAPI GL 参数。

## Verification Commands

从项目根目录运行：

```powershell
py -m pytest backend/tests
py -m ruff check backend/travel_agent backend/tests
```

前端从 `frontend/` 目录运行：

```powershell
npm run typecheck
npm run test --if-present
npm run build
```

Docker 验证从项目根目录运行：

```powershell
docker compose up --build
```

如果因为缺少依赖、密钥或本地服务无法运行验证，最终回复必须说明没有运行的命令和原因。
