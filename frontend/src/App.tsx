import { useEffect, useState, type ChangeEvent } from 'react'
import { SidebarPanel, type SidebarHistoryEntry } from './SidebarPanel'
import { AnswerResult } from './components/AnswerResult'
import { ChatComposer } from './components/ChatComposer'
import { MessageBubble as ChatMessageBubble } from './components/MessageBubble'
import { QUICK_ACTIONS, buildChatTextFields, buildTravelPlanChatSummary, createQuickActionDraft, getResponseResultKind, getUploadContextPreview } from './chatUi'
import { limitPlanDays, replacePlanResult } from './planDisplay'

type Role = 'user' | 'assistant'

type Message = {
  role: Role
  content: string
}

type RouteStep = {
  instruction: string
  distance?: string | null
  duration?: string | null
  road_name?: string | null
  direction?: string | null
  action?: string | null
}

type RouteOption = {
  title: string
  summary: string
  distance: string
  duration: string
  reasons: string[]
  steps: RouteStep[]
  mode?: string | null
  tags?: string[]
  toll?: number | string | null
  traffic_light_count?: number | null
  waypoint_summary?: string | null
}

type ScenicHighlight = {
  title: string
  detail?: string
}

type TransportBlock = {
  mode?: string
  label?: string
  origin?: string
  destination?: string
  ride_minutes?: number | string
  buffer_minutes?: number | string
  total_minutes?: number | string
  summary?: string
}

type RouteDebug = {
  generated_at?: string
  origin_point?: string | null
  destination_point?: string | null
  best_option?: RouteOption
  weather_hint?: string
  attractions?: string[]
  hotel_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  food_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  request_debug?: Record<string, unknown>
  trip_profile?: Record<string, unknown>
  weather_context?: WeatherContext
  weather_plan_summary?: WeatherPlanSummary
  waypoint_details?: WaypointDetail[]
  must_visit_attractions?: string[]
  waypoint_order_mode?: string
  unscheduled_waypoints?: string[]
  backup_waypoints?: { name?: string; reason?: string; tags?: string }[]
  reservation_tips?: string[]
  stage_segments?: { transport_block?: TransportBlock }[]
}

type WeatherDay = {
  day?: number
  city?: string
  weather?: string
  temperature?: string
  outdoor_suitability?: string
  indoor_priority?: boolean
  strategy?: string
  weather_tips?: string[]
  packing_tips?: string[]
  weather_tags?: string[]
  data_source?: string
  fallback_reason?: string | null
  adcode?: string | null
}

type WeatherContext = {
  data_source?: string
  summary?: string
  daily_weather?: WeatherDay[]
  request_debug?: Record<string, unknown>
}

type WeatherPlanSummary = {
  weather_overview?: string
  daily_weather_briefs?: string[]
  weather_adjustments?: string[]
  packing_summary?: string[]
}

type WeatherQueryData = {
  city?: string
  adcode?: string | null
  connected?: boolean
  data_source?: string
  fallback_reason?: string | null
  summary?: string
  daily_weather?: WeatherDay[]
  weather_tips?: string[]
  packing_tips?: string[]
  debug?: Record<string, unknown>
  response_meta?: Record<string, unknown>
}

type ConversationTurn = {
  user_input: string
  assistant_output: string
}

type ConversationSummary = {
  conversation_id: string
  title?: string
  last_user_input?: string
  last_assistant_output?: string
  updated_at?: string
  intent?: string
}

type MemoryStatus = {
  backend?: string
  connected?: boolean
  fallback_reason?: string
  [key: string]: unknown
}

type ConversationListResponse = {
  conversations?: ConversationSummary[]
  meta?: { memory?: MemoryStatus }
}

type ConversationHistoryResponse = {
  conversation_id?: string
  history?: ConversationTurn[]
  meta?: { memory?: MemoryStatus }
}

type WaypointDetail = {
  name: string
  type?: string
  must_visit?: boolean
  source?: string
  order?: number
}

type TripDayPlan = {
  day: number
  title: string
  stage?: 'route' | 'destination' | 'buffer' | string
  anchor_city?: string | null
  route_segment?: string
  segment_data_source?: string | null
  drive_time?: string
  visit_time?: string
  weather_strategy?: string | null
  weather_summary?: string
  weather_adjustments?: string[]
  weather_badge?: string | null
  weather_tips?: string[]
  packing_tips?: string[]
  weather_tags?: string[]
  transport_block?: TransportBlock | null
  morning: string
  afternoon: string
  evening: string
  attractions?: { name: string; address?: string; category?: string; reason?: string; tags?: string; must_visit?: string }[]
  backup_attractions?: { name: string; address?: string; category?: string; reason?: string; tags?: string; must_visit?: string }[]
  reservation_tips?: string[]
  meals?: string[]
  hotel_hint?: string | null
  recommendation_reasons?: string[]
  tags?: string[]
  notes?: string[]
}

type TravelPlanResponse = {
  conversation_id: string
  intent: string
  scenario: string
  summary: string
  route_title: string
  trip_type?: string
  route_total_duration?: string
  route_total_distance?: string
  trip_overview?: string
  duration_days?: number
  budget_estimate?: string
  accommodation_suggestion?: string
  transportation_suggestion?: string[]
  weather_hint?: string
  weather_overview?: string
  weather_adjustments?: string[]
  packing_summary?: string[]
  attraction_recommendations?: string[]
  hotel_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  food_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  scenic_route_highlights?: string[]
  route_highlights?: ScenicHighlight[]
  daily_itinerary?: TripDayPlan[]
  travel_tips?: string[]
  route_steps?: RouteStep[]
  route_options?: RouteOption[]
  recommendation_reasons?: string[]
  user_preferences?: string[]
  history?: ConversationTurn[]
  raw_route?: Record<string, unknown>
  response_meta?: Record<string, unknown>
  data_source?: string
  confidence?: string
  route_error?: string | null
}

type UploadContext = {
  filename: string
  content_type: string
  size: number
  file_kind?: string
  extracted_text?: string
  extraction_error?: string
  audio_debug?: Record<string, unknown>
}

type AudioDebugPanel = {
  input_suffix?: string
  content_type?: string
  input_size?: number
  converted_size?: number
  status_code?: number
  response_keys?: string[]
  result_type?: string
  transcript_preview?: string
  choices_count?: number
  choice_keys?: string[]
  stage?: string
  error_type?: string
  error_message?: string
}

type TravelRequestDebug = {
  origin?: string
  destination?: string
  travel_mode?: string
  preferences?: string | null
  source_query?: string | null
  trip_profile?: Record<string, unknown>
  waypoint_order?: boolean
  waypoints?: { name: string }[]
}

type NearbyCandidate = {
  name: string
  address?: string
  category?: string
  location?: string
  id?: string
}

type NearbyDebug = {
  city?: string
  anchor?: string
  anchor_point?: string | null
  anchor_debug?: Record<string, unknown> | null
  destination_point?: string | null
  attraction_recommendations?: string[]
  transportation_suggestion?: string[]
  hotel_candidates?: NearbyCandidate[]
  food_candidates?: NearbyCandidate[]
  debug?: Record<string, unknown> | null
}

type UnifiedChatResponse = {
  conversation_id: string
  answer_type: 'travel_planning' | 'nearby_search' | 'general_chat' | 'weather_query'
  final_answer: string
  data?: {
    travel_plan?: TravelPlanResponse | null
    nearby?: NearbyDebug | null
    weather?: WeatherQueryData | null
  }
  travel_request?: TravelRequestDebug | null
  upload_context?: UploadContext | null
  meta?: Record<string, unknown>
  error?: string | null
}

const HISTORY_KEY = 'travel-agent-ui-history'
const CONVERSATION_KEY = 'travel-agent-ui-conversation-id'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || '/api'
const apiUrl = (path: string) => `${API_BASE_URL}${path}`

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function normalizeHistory(raw: unknown): ConversationTurn[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((item): item is ConversationTurn => Boolean(item && typeof item.user_input === 'string' && typeof item.assistant_output === 'string'))
}

function normalizeConversationSummaries(raw: unknown): ConversationSummary[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is ConversationSummary => Boolean(item && typeof item.conversation_id === 'string'))
    .map((item) => ({
      conversation_id: item.conversation_id,
      title: typeof item.title === 'string' ? item.title : '',
      last_user_input: typeof item.last_user_input === 'string' ? item.last_user_input : '',
      last_assistant_output: typeof item.last_assistant_output === 'string' ? item.last_assistant_output : '',
      updated_at: typeof item.updated_at === 'string' ? item.updated_at : '',
      intent: typeof item.intent === 'string' ? item.intent : '',
    }))
}

function normalizeTravelPlan(raw: unknown): TravelPlanResponse | null {
  if (!isObject(raw)) return null
  const candidate = raw as TravelPlanResponse
  return {
    ...candidate,
    route_steps: candidate.route_steps || [],
    route_options: candidate.route_options || [],
    recommendation_reasons: candidate.recommendation_reasons || [],
    user_preferences: candidate.user_preferences || [],
    history: candidate.history || [],
    transportation_suggestion: candidate.transportation_suggestion || [],
    attraction_recommendations: candidate.attraction_recommendations || [],
    daily_itinerary: limitPlanDays(candidate.daily_itinerary, candidate.duration_days),
    travel_tips: candidate.travel_tips || [],
  }
}

function normalizeUnifiedResponse(raw: unknown): UnifiedChatResponse | null {
  if (!isObject(raw)) return null
  const candidate = raw as UnifiedChatResponse
  return {
    conversation_id: typeof candidate.conversation_id === 'string' ? candidate.conversation_id : '',
    answer_type: candidate.answer_type || 'general_chat',
    final_answer: typeof candidate.final_answer === 'string' ? candidate.final_answer : '',
    data: isObject(candidate.data) ? candidate.data : {},
    travel_request: isObject(candidate.travel_request) ? candidate.travel_request as TravelRequestDebug : null,
    upload_context: isObject(candidate.upload_context) ? candidate.upload_context as UploadContext : null,
    meta: isObject(candidate.meta) ? candidate.meta : {},
    error: typeof candidate.error === 'string' ? candidate.error : null,
  }
}

function formatHistoryTitle(text: string) {
  const match = text.match(/从?([^，。；,]+?)(?:自驾|驾车|开车|公交|公共交通|地铁|骑行|步行)?(?:到|去)([^，。；,]+?)(?:\d|三|两|一|，|,|。|$)/)
  if (match) return `${match[1].replace(/^从/, '').trim()} -> ${match[2].trim()}`
  return text.length > 18 ? `${text.slice(0, 18)}...` : text
}

export default function App() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState(() => localStorage.getItem(CONVERSATION_KEY) || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [upload, setUpload] = useState<File | null>(null)
  const [uploadPreview, setUploadPreview] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [uploadKind, setUploadKind] = useState<'image' | 'audio' | 'other' | ''>('')
  const [audioDebug, setAudioDebug] = useState<AudioDebugPanel | null>(null)
  const [lastAudioDebugText, setLastAudioDebugText] = useState('')
  const [result, setResult] = useState<TravelPlanResponse | null>(null)
  const [weatherResult, setWeatherResult] = useState<WeatherQueryData | null>(null)
  const [history, setHistory] = useState<ConversationTurn[]>(() => {
    try {
      return normalizeHistory(JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'))
    } catch {
      return []
    }
  })
  const [conversationSummaries, setConversationSummaries] = useState<ConversationSummary[]>([])
  const [memoryStatus, setMemoryStatus] = useState<MemoryStatus | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    if (conversationId) localStorage.setItem(CONVERSATION_KEY, conversationId)
  }, [conversationId])

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history))
  }, [history])

  const hasUpload = Boolean(upload)
  const canSend = (input.trim().length > 0 || hasUpload) && !loading
  const memoryLabel = memoryStatus ? (memoryStatus.connected ? 'Redis 已连接' : '内存 fallback') : '服务端历史'

  const refreshConversationList = async () => {
    try {
      const response = await fetch(apiUrl('/chat/conversations'))
      if (!response.ok) throw new Error(`历史记录请求失败 ${response.status}`)
      const data = (await response.json()) as ConversationListResponse
      setConversationSummaries(normalizeConversationSummaries(data.conversations))
      if (data.meta?.memory) setMemoryStatus(data.meta.memory)
    } catch {
      setConversationSummaries([])
    }
  }

  useEffect(() => {
    void refreshConversationList()
  }, [])

  const resetUploadState = () => {
    setUploadPreview('')
    setUploadError('')
    setUploadKind('')
    setAudioDebug(null)
    setLastAudioDebugText('')
  }

  const applyUploadContext = (uploadContext?: UploadContext | null) => {
    if (!uploadContext) return
    setUploadKind((uploadContext.file_kind as 'image' | 'audio' | 'other' | '') || '')
    if (uploadContext.file_kind === 'audio') {
      setAudioDebug((uploadContext.audio_debug as AudioDebugPanel | undefined) || null)
      if (import.meta.env.DEV && uploadContext.audio_debug) {
        const debugText = Object.entries(uploadContext.audio_debug)
          .filter(([, value]) => value !== undefined && value !== null && value !== '')
          .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
          .join('\n')
        setLastAudioDebugText(debugText)
      }
      if (uploadContext.extracted_text) {
        setUploadError('')
      } else {
        setUploadPreview((prev) => prev || '语音文件已上传，但尚未识别出文本')
        setUploadError(uploadContext.extraction_error ? `语音识别失败：${uploadContext.extraction_error}` : '语音识别失败')
      }
      return
    }
    setAudioDebug(null)
    const preview = getUploadContextPreview(uploadContext)
    setUploadPreview(preview.preview)
    setUploadError(preview.error)
    if (preview.shouldUseExtractedText) setInput(preview.preview)
  }

  const syncResponseState = (data: UnifiedChatResponse) => {
    setConversationId(data.conversation_id || '')
    applyUploadContext(data.upload_context)
    const memory = data.meta?.memory
    if (isObject(memory)) setMemoryStatus(memory as MemoryStatus)

    const answerType = data.answer_type || 'general_chat'
    const travelPlan = normalizeTravelPlan(data.data?.travel_plan)
    const nearby = data.data?.nearby
    const weather = data.data?.weather
    const resultKind = getResponseResultKind(answerType, {
      hasTravelPlan: Boolean(travelPlan),
      hasWeather: Boolean(weather),
    })

    if (resultKind === 'nearby') {
      setResult(null)
      setWeatherResult(null)
      const hotels = nearby?.hotel_candidates?.length
        ? `酒店：${nearby.hotel_candidates.slice(0, 3).map((item) => `${item.name}${item.address ? `（${item.address}）` : item.location ? `（${item.location}）` : ''}`).join('；')}`
        : '酒店：没有'
      const foods = nearby?.food_candidates?.length
        ? `餐厅：${nearby.food_candidates.slice(0, 3).map((item) => `${item.name}${item.address ? `（${item.address}）` : item.location ? `（${item.location}）` : ''}`).join('；')}`
        : '餐厅：没有'
      const attractions = nearby?.attraction_recommendations?.length
        ? `景点：${nearby.attraction_recommendations.slice(0, 5).join('；')}`
        : '景点：没有'
      const nearbyText = [hotels, foods, attractions].join('\n')
      setMessages((prev) => [...prev, { role: 'assistant', content: nearbyText }])
    } else if (resultKind === 'travel' && travelPlan) {
      setResult((current) => replacePlanResult(current, { ...travelPlan, response_meta: data.meta }))
      setWeatherResult(null)
      setHistory(travelPlan.history || [])
      setMessages((prev) => [...prev, { role: 'assistant', content: buildTravelPlanChatSummary(travelPlan) }])
    } else if (resultKind === 'weather' && weather) {
      setResult(null)
      setWeatherResult({ ...weather, response_meta: data.meta })
      setMessages((prev) => [...prev, { role: 'assistant', content: data.final_answer || weather.summary || '暂无天气结果' }])
    } else {
      setResult(null)
      setWeatherResult(null)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.final_answer || '暂无结果' }])
    }
    void refreshConversationList()
  }

  const requestChat = async (questionText: string) => {
    const buildFormData = () => {
      const formData = new FormData()
      buildChatTextFields({ question: questionText, conversationId }).forEach(([name, value]) => formData.append(name, value))
      if (upload) {
        if (upload.type.startsWith('audio/')) {
          formData.append('audio', upload)
        } else {
          formData.append('image', upload)
        }
      }
      return formData
    }

    const endpoints = [apiUrl('/chat/multimodal'), apiUrl('/multimodal')]
    let lastError: unknown = null

    for (const endpoint of endpoints) {
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          body: buildFormData(),
        })
        if (response.status === 404) continue
        if (!response.ok) {
          const text = await response.text().catch(() => '')
          throw new Error(text || `请求失败 ${response.status}`)
        }
        return (await response.json()) as UnifiedChatResponse
      } catch (err) {
        lastError = err
      }
    }

    throw lastError instanceof Error ? lastError : new Error('未能连接到后端，请检查 API 地址与代理配置')
  }

  const runChat = async (overrideQuestion?: string) => {
    const questionText = (overrideQuestion ?? input).trim() || (hasUpload ? '请根据我上传的内容进行回答' : '')
    if (!questionText && !hasUpload) return

    setLoading(true)
    setError('')
    setResult(null)
    setWeatherResult(null)
    setMessages((prev) => [...prev, { role: 'user', content: questionText }])

    try {
      const data = await requestChat(questionText)
      syncResponseState(data)
      setInput('')
      setUpload(null)
      resetUploadState()
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误')
      setResult(null)
      setWeatherResult(null)
    } finally {
      setLoading(false)
    }
  }

  const applyHistory = (item: ConversationTurn) => {
    setInput(item.user_input)
    setMessages((prev) => [...prev, { role: 'assistant', content: item.assistant_output }])
  }

  const applyConversationSummary = async (item: ConversationSummary) => {
    setConversationId(item.conversation_id)
    setInput(item.last_user_input || '')
    try {
      const response = await fetch(apiUrl(`/chat/history/${encodeURIComponent(item.conversation_id)}`))
      if (!response.ok) throw new Error(`会话历史请求失败 ${response.status}`)
      const data = (await response.json()) as ConversationHistoryResponse
      const turns = normalizeHistory(data.history || [])
      setHistory(turns)
      if (data.meta?.memory) setMemoryStatus(data.meta.memory)
      if (turns.length) {
        setMessages(turns.flatMap((turn) => [
          { role: 'user' as const, content: turn.user_input },
          { role: 'assistant' as const, content: turn.assistant_output },
        ]))
        setInput(turns[turns.length - 1]?.user_input || item.last_user_input || '')
      } else {
        setMessages([{ role: 'assistant', content: item.last_assistant_output || '该会话暂无可展示的短期历史。' }])
      }
      setResult(null)
      setWeatherResult(null)
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: item.last_assistant_output || '暂时无法读取该会话历史。' }])
    }
  }

  const startNewConversation = () => {
    setMessages([])
    setResult(null)
    setWeatherResult(null)
    setConversationId('')
    setInput('')
    setError('')
    setUpload(null)
    resetUploadState()
    setSidebarOpen(false)
    localStorage.removeItem(CONVERSATION_KEY)
  }

  const historyEntries: SidebarHistoryEntry[] = conversationSummaries.length
    ? conversationSummaries.map((item) => ({
      id: item.conversation_id,
      title: item.title || formatHistoryTitle(item.last_user_input || item.conversation_id),
      summary: item.last_assistant_output || item.last_user_input || '暂无摘要',
      updatedAt: item.updated_at,
      active: item.conversation_id === conversationId,
    }))
    : history.map((item, index) => ({
      id: `local-${index}`,
      title: formatHistoryTitle(item.user_input),
      summary: item.assistant_output,
    }))

  const selectHistoryEntry = (id: string) => {
    const summary = conversationSummaries.find((item) => item.conversation_id === id)
    if (summary) {
      void applyConversationSummary(summary)
    } else if (id.startsWith('local-')) {
      const item = history[Number(id.slice(6))]
      if (item) applyHistory(item)
    }
    setSidebarOpen(false)
  }

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] || null
    setUpload(selected)
    resetUploadState()
    if (!selected) {
      setUploadKind('')
      return
    }

    const isAudio = selected.type.startsWith('audio/') || /\.(mp3|wav|m4a|aac|ogg|webm|flac|opus|amr|3gp)$/i.test(selected.name)
    const isImage = selected.type.startsWith('image/')
    const isTextLike = !isAudio && !isImage && /\.(txt|md|csv|log|json)$/i.test(selected.name)
    setUploadKind(isAudio ? 'audio' : isImage ? 'image' : 'other')

    if (isTextLike) {
      try {
        const text = await selected.text()
        const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
        if (normalized) {
          setInput(normalized)
          setUploadPreview(normalized)
        }
      } catch {
        // Server extraction remains available when local preview fails.
      }
    }
  }

  const clearComposer = () => {
    setInput('')
    setUpload(null)
    resetUploadState()
    setAudioDebug(null)
    setLastAudioDebugText('')
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          type="button"
          className="icon-button history-toggle"
          title="打开历史记录"
          aria-label="打开历史记录"
          aria-controls="workspace-sidebar"
          aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen(true)}
        >☰</button>
        <div className="brand-block">
          <p className="eyebrow">AI 出行 Agent</p>
          <h1>智能旅游规划工作台</h1>
          <p className="subtitle">在对话中描述完整需求，统一生成路线、天气与交通安排。</p>
        </div>
        <div className="topbar-actions">
          <span className="status-pill">{conversationId ? `会话 ${conversationId.slice(0, 8)}` : '新会话'}</span>
          <button type="button" className="icon-button" title="新建会话" aria-label="新建会话" onClick={startNewConversation}>＋</button>
        </div>
      </header>

      {sidebarOpen ? <button type="button" className="sidebar-scrim" aria-label="关闭历史侧栏" onClick={() => setSidebarOpen(false)} /> : null}

      <main className="workspace answer-layout">
        <aside id="workspace-sidebar" className={`left-panel${sidebarOpen ? ' open' : ''}`}>
          <SidebarPanel
            quickActions={QUICK_ACTIONS}
            historyEntries={historyEntries}
            memoryLabel={memoryLabel}
            memoryConnected={Boolean(memoryStatus?.connected)}
            onSelectPrompt={(action) => {
              const draft = createQuickActionDraft(action)
              setInput(draft.input)
              setSidebarOpen(false)
            }}
            onSelectHistory={selectHistoryEntry}
            onNewConversation={startNewConversation}
            onClose={() => setSidebarOpen(false)}
          />
        </aside>

        <section className="center-panel chat-card answer-card">
          <div className="section-head">
            <h2>旅行规划助手</h2>
            <span className="muted">像对话一样直接给出路线、天气和行程结果</span>
          </div>

          <div className="chat-stream">
            {messages.length === 0 ? (
              <div className="empty-chat">
                <h3>开始提问吧</h3>
                <p>请直接写明出发地、目的地、天数、交通方式、途经城市和游览偏好。</p>
              </div>
            ) : messages.map((message, index) => <ChatMessageBubble key={`${message.role}-${index}`} message={message} />)}
            {loading ? <div className="message assistant loading-message" role="status"><span className="message-role">Agent</span><p>正在分析路线、天气与交通安排…</p></div> : null}
            <AnswerResult plan={result} weather={weatherResult} />
          </div>

          <ChatComposer
            input={input}
            loading={loading}
            canSend={canSend}
            uploadName={upload?.name || ''}
            uploadKind={uploadKind}
            uploadPreview={uploadPreview}
            uploadError={uploadError}
            error={error}
            lastAudioDebugText={lastAudioDebugText}
            showAudioDebug={import.meta.env.DEV}
            onInputChange={setInput}
            onFileChange={handleFileChange}
            onClear={clearComposer}
            onSend={() => runChat()}
          />
        </section>
      </main>
    </div>
  )
}
