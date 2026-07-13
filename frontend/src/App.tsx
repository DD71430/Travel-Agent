import { useEffect, useMemo, useState } from 'react'

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

type RouteDebug = {
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
  waypoint_details?: WaypointDetail[]
  must_visit_attractions?: string[]
  waypoint_order_mode?: string
  unscheduled_waypoints?: string[]
}

type WeatherDay = {
  day?: number
  city?: string
  weather?: string
  temperature?: string
  outdoor_suitability?: string
  indoor_priority?: boolean
  strategy?: string
}

type WeatherContext = {
  data_source?: string
  summary?: string
  daily_weather?: WeatherDay[]
}

type ConversationTurn = {
  user_input: string
  assistant_output: string
}

type Waypoint = {
  name: string
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
  morning: string
  afternoon: string
  evening: string
  attractions?: { name: string; address?: string; category?: string; reason?: string; tags?: string; must_visit?: string }[]
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
  waypoints?: Waypoint[]
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
  answer_type: 'travel_planning' | 'nearby_search' | 'general_chat'
  final_answer: string
  data?: {
    travel_plan?: TravelPlanResponse | null
    nearby?: NearbyDebug | null
  }
  travel_request?: TravelRequestDebug | null
  upload_context?: UploadContext | null
  meta?: Record<string, unknown>
  error?: string | null
}

type PlanForm = {
  origin: string
  destination: string
  preferences: string
  travel_mode: 'driving' | 'walking' | 'transit' | 'bicycling'
  waypoint_order: boolean
  waypoints: Waypoint[]
}

const defaultForm: PlanForm = {
  origin: '',
  destination: '',
  preferences: '',
  travel_mode: 'driving',
  waypoint_order: false,
  waypoints: [],
}

const HISTORY_KEY = 'travel-agent-ui-history'
const FORM_KEY = 'travel-agent-ui-form'
const CONVERSATION_KEY = 'travel-agent-ui-conversation-id'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || '/api'
const apiUrl = (path: string) => `${API_BASE_URL}${path}`

const TRAVEL_MODES: PlanForm['travel_mode'][] = ['driving', 'walking', 'transit', 'bicycling']
const TRAVEL_MODE_LABELS: Record<PlanForm['travel_mode'], string> = {
  driving: '驾车',
  walking: '步行',
  transit: '公交',
  bicycling: '骑行',
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function detectQuestionIntent(text: string): 'nearby' | 'travel' | 'general' {
  const source = text.trim()
  if (/(附近|周边|酒店|餐厅|美食|景点|博物馆|公园|商场)/.test(source)) return 'nearby'
  if (/(路线|规划|行程|从.+到.+|怎么去|怎么走|出发|目的地|途经|一日游|两天一晚|三天两晚|旅游|攻略)/.test(source)) return 'travel'
  return 'general'
}

function normalizeForm(raw: unknown): PlanForm {
  const candidate = isObject(raw) ? (raw as Partial<PlanForm>) : {}
  return {
    origin: typeof candidate.origin === 'string' ? candidate.origin : defaultForm.origin,
    destination: typeof candidate.destination === 'string' ? candidate.destination : defaultForm.destination,
    preferences: typeof candidate.preferences === 'string' ? candidate.preferences : defaultForm.preferences,
    travel_mode: candidate.travel_mode && TRAVEL_MODES.includes(candidate.travel_mode) ? candidate.travel_mode : defaultForm.travel_mode,
    waypoint_order: typeof candidate.waypoint_order === 'boolean' ? candidate.waypoint_order : defaultForm.waypoint_order,
    waypoints: Array.isArray(candidate.waypoints)
      ? candidate.waypoints.filter((item): item is Waypoint => Boolean(item && typeof item.name === 'string')).map((item) => ({ name: item.name }))
      : [],
  }
}

function normalizeHistory(raw: unknown): ConversationTurn[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((item): item is ConversationTurn => Boolean(item && typeof item.user_input === 'string' && typeof item.assistant_output === 'string'))
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
    daily_itinerary: candidate.daily_itinerary || [],
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

function getDataSourceLabel(value?: string) {
  if (!value) return 'unknown'
  if (value === 'tencent_maps') return '腾讯地图真实返回'
  if (value === 'weather_service') return '实时天气参考'
  if (value === 'poi_search') return '周边 POI 真实返回'
  return `fallback(${value})`
}


function createQuickPrompt(mode: 'travel' | 'nearby') {
  const prompts = {
    travel: '帮我规划一个三天两晚的旅行路线，优先经典景点和合理游览节奏',
    nearby: '推荐北京故宫附近的酒店、餐厅和景点',
  }
  return prompts[mode]
}

function getTripTypeLabel(value?: string, stageMode?: unknown) {
  if (stageMode === 'route_then_destination') return '沿途 + 目的地'
  if (stageMode === 'destination_only') return '目的地深度游'
  if (stageMode === 'route_only') return '沿途游'
  if (value === 'along_route_trip') return '沿途游'
  if (value === 'destination_trip') return '目的地游'
  return value || '未分类'
}

function getStageLabel(value?: string) {
  if (value === 'route') return '沿途阶段'
  if (value === 'destination') return '目的地阶段'
  if (value === 'buffer') return '机动/返程'
  return '行程阶段'
}

function dedupeStrings(items?: string[]) {
  const result: string[] = []
  for (const item of items || []) {
    const cleaned = item.trim()
    if (cleaned && !result.includes(cleaned)) result.push(cleaned)
  }
  return result
}

function getDisplayNotes(day: TripDayPlan) {
  const meals = new Set(dedupeStrings(day.meals))
  const hotelHint = day.hotel_hint || ''
  return dedupeStrings(day.notes).filter((note) => {
    if (note.startsWith('午餐') || note.startsWith('晚餐') || note.startsWith('住宿')) return false
    if (meals.has(note)) return false
    if (hotelHint && note === hotelHint) return false
    return true
  })
}

function getProfileNumber(profile: Record<string, unknown> | null | undefined, key: string) {
  const value = profile?.[key]
  if (typeof value === 'number') return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function getWeatherBadge(day?: WeatherDay, isFallback = false) {
  if (!day) return '天气待确认'
  if (isFallback) return '天气待确认'
  if (day.indoor_priority) return '室内优先'
  if (day.outdoor_suitability === 'good') return '室外适合'
  return '天气参考'
}

function formatWeatherDay(day: WeatherDay, isFallback: boolean) {
  if (isFallback) return `${day.city || '目的地'} · 天气待确认`
  return `${day.city || '目的地'} · ${day.weather || '天气待确认'} · ${day.temperature || '温度待确认'}`
}

function getWaypointOrderLabel(value?: string) {
  if (value === 'user_order') return '按输入顺序'
  if (value === 'optimize') return '系统优化'
  return '未指定'
}

function ToolChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="chip" onClick={onClick}>
      {label}
    </button>
  )
}

function PlanCard({ plan }: { plan: TravelPlanResponse }) {
  const routeDebug = isObject(plan.raw_route) ? (plan.raw_route as RouteDebug) : null
  const tripProfile = isObject(routeDebug?.trip_profile)
    ? routeDebug?.trip_profile
    : isObject(routeDebug?.request_debug)
      ? routeDebug?.request_debug
      : null
  const routeDays = getProfileNumber(tripProfile, 'route_days')
  const destinationDays = getProfileNumber(tripProfile, 'destination_days')
  const bufferDays = getProfileNumber(tripProfile, 'buffer_days')
  const weatherContext = isObject(routeDebug?.weather_context) ? routeDebug?.weather_context : null
  const dailyWeather = Array.isArray(weatherContext?.daily_weather) ? weatherContext?.daily_weather : []
  const waypointDetails = Array.isArray(routeDebug?.waypoint_details) ? routeDebug?.waypoint_details : []
  const mustVisitAttractions = Array.isArray(routeDebug?.must_visit_attractions) ? routeDebug?.must_visit_attractions : []
  const unscheduledWaypoints = Array.isArray(routeDebug?.unscheduled_waypoints) ? routeDebug?.unscheduled_waypoints : []
  const routeHighlights = plan.route_highlights || []
  const scenicTexts = plan.attraction_recommendations || []
  return (
    <div className="plan-card">
      <div className="plan-hero">
        <div>
          <h3>{plan.route_title}</h3>
          <p>{plan.trip_overview || plan.summary}</p>
        </div>
        <span className="status-badge">{getDataSourceLabel(plan.data_source)}</span>
      </div>
      {plan.data_source && plan.data_source !== 'tencent_maps' ? (
        <div className="fallback-banner">当前为兜底规划，真实路线、营业时间和票务信息请以出行前查询为准。</div>
      ) : null}
      {weatherContext?.data_source === 'fallback' ? (
        <div className="weather-banner">天气待确认，建议出行前查看实时天气；本行程保留室内/室外备选。</div>
      ) : null}
      {unscheduledWaypoints.length ? (
        <div className="fallback-banner">未安排途经点/景点：{unscheduledWaypoints.join('、')}。建议延长停留或作为备选。</div>
      ) : null}

      <div className="plan-meta-grid">
        <div><span>意图</span><strong>{plan.intent}</strong></div>
        <div><span>场景</span><strong>{plan.scenario}</strong></div>
        <div><span>行程类型</span><strong>{getTripTypeLabel(plan.trip_type, tripProfile?.stage_plan_mode)}</strong></div>
        <div><span>天数</span><strong>{plan.duration_days || '--'} 天</strong></div>
        <div><span>沿途天数</span><strong>{routeDays ?? 0} 天</strong></div>
        <div><span>目的地天数</span><strong>{destinationDays ?? 0} 天</strong></div>
        {bufferDays ? <div><span>机动天数</span><strong>{bufferDays} 天</strong></div> : null}
        <div><span>出行方式</span><strong>{String(routeDebug?.request_debug?.travel_mode || '--')}</strong></div>
        <div><span>总距离</span><strong>{plan.route_total_distance || routeDebug?.best_option?.distance || '--'}</strong></div>
        <div><span>总耗时</span><strong>{plan.route_total_duration || routeDebug?.best_option?.duration || '--'}</strong></div>
        <div><span>天气参考</span><strong>{plan.weather_hint || '以出行前最新天气为准'}</strong></div>
        <div><span>途经点</span><strong>{waypointDetails.length ? waypointDetails.map((item) => item.name).join('、') : '--'}</strong></div>
        <div><span>必去景点</span><strong>{mustVisitAttractions.length ? mustVisitAttractions.join('、') : '--'}</strong></div>
        <div><span>顺序模式</span><strong>{getWaypointOrderLabel(routeDebug?.waypoint_order_mode)}</strong></div>
      </div>

      <div className="highlight-strip">
        <div>
          <span>路程拆分</span>
          <strong>{plan.transportation_suggestion?.[0] || plan.trip_overview || '已按实际路程时间进行行程切分'}</strong>
        </div>
        <div>
          <span>天气策略</span>
          <strong>{weatherContext?.summary || plan.weather_hint || '根据实时天气动态调整室内外景点'}</strong>
        </div>
        <div>
          <span>景点串联</span>
          <strong>{routeHighlights[0]?.title || plan.scenic_route_highlights?.[0] || '已优先串联相邻景点并按游览节奏排序'}</strong>
        </div>
      </div>

      <div className="plan-section">
        <h4>推荐景点</h4>
        <ul>
          {scenicTexts.slice(0, 6).map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>

      <div className="plan-footer-grid">
        <div className="plan-section">
          <h4>景点串联路线</h4>
          <ul>
            {routeHighlights.length ? routeHighlights.slice(0, 5).map((item) => <li key={item.title}>{item.title}{item.detail ? `：${item.detail}` : ''}</li>) : (plan.scenic_route_highlights || []).slice(0, 4).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
        <div className="plan-section">
          <h4>路程与天气要点</h4>
          <ul>
            {(plan.transportation_suggestion || []).slice(0, 4).map((item) => <li key={item}>{item}</li>)}
            {routeDebug?.origin_point ? <li>出发点坐标：{routeDebug.origin_point}</li> : null}
            {routeDebug?.destination_point ? <li>目的地坐标：{routeDebug.destination_point}</li> : null}
          </ul>
        </div>
      </div>

      <div className="itinerary-list">
        {(plan.daily_itinerary || []).map((day) => (
          <article key={day.day} className="day-card">
            {(() => {
              const weatherDay = dailyWeather[day.day - 1]
              const isFallbackWeather = weatherContext?.data_source === 'fallback'
              return weatherDay ? (
                <div className="weather-chip-row">
                  <span>{formatWeatherDay(weatherDay, isFallbackWeather)}</span>
                  <strong>{getWeatherBadge(weatherDay, isFallbackWeather)}</strong>
                  <small>{isFallbackWeather ? '保留室内/室外备选' : weatherDay.strategy}</small>
                </div>
              ) : null
            })()}
            <div className="day-card-head">
              <strong>第{day.day}天</strong>
              <span>{day.title}{day.anchor_city ? ` · ${day.anchor_city}` : ''}</span>
              <em>{getStageLabel(day.stage)}</em>
            </div>
            <p><b>路线段：</b>{day.route_segment || '按当日景点顺序串联'}；<b>当天城市：</b>{day.anchor_city || '按行程'}；<b>行驶/转场：</b>{day.drive_time || '按实时路况'}；<b>可游玩：</b>{day.visit_time || '约半天至全天'}</p>
            <p><b>上午：</b>{day.morning}</p>
            <p><b>下午：</b>{day.afternoon}</p>
            <p><b>晚上：</b>{day.evening}</p>
            {day.attractions?.length ? (
              <div className="note-row">
                {day.attractions.map((item) => <span key={`${day.day}-${item.name}`}>{item.name}{item.must_visit === 'true' ? ' · 必去' : ''}{item.tags ? ` · ${item.tags}` : ''}</span>)}
              </div>
            ) : null}
            {day.recommendation_reasons?.length ? (
              <ul>
                {dedupeStrings(day.recommendation_reasons).slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            ) : null}
            {day.meals?.length ? <p><b>餐饮：</b>{dedupeStrings(day.meals).join(' ')}</p> : null}
            {day.hotel_hint ? <p><b>住宿：</b>{day.hotel_hint}</p> : null}
            {getDisplayNotes(day).length ? (
              <div className="note-row">
                {getDisplayNotes(day).map((note) => <span key={note}>{note}</span>)}
              </div>
            ) : null}
          </article>
        ))}
      </div>

      <div className="plan-footer-grid">
        <div className="plan-section">
          <h4>交通建议</h4>
          <ul>
            {(plan.transportation_suggestion || []).slice(0, 4).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
        <div className="plan-section">
          <h4>旅行贴士</h4>
          <ul>
            {(plan.travel_tips || []).slice(0, 4).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  return (
    <article className={`message ${message.role}`}>
      <span className="message-role">{message.role === 'user' ? '我' : 'Agent'}</span>
      <p>{message.content}</p>
    </article>
  )
}

export default function App() {
  const [form, setForm] = useState<PlanForm>(() => {
    try {
      return normalizeForm(JSON.parse(localStorage.getItem(FORM_KEY) || 'null'))
    } catch {
      return defaultForm
    }
  })
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
  const [history, setHistory] = useState<ConversationTurn[]>(() => {
    try {
      return normalizeHistory(JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'))
    } catch {
      return []
    }
  })

  useEffect(() => {
    localStorage.setItem(FORM_KEY, JSON.stringify(form))
  }, [form])

  useEffect(() => {
    if (conversationId) localStorage.setItem(CONVERSATION_KEY, conversationId)
  }, [conversationId])

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history))
  }, [history])

  const hasUpload = Boolean(upload)
  const canSend = (input.trim().length > 0 || hasUpload) && !loading
  const canPlan = form.origin.trim().length > 0 && form.destination.trim().length > 0 && !loading

  const updateField = <K extends keyof PlanForm>(key: K, value: PlanForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const updateWaypoint = (index: number, value: string) => {
    setForm((prev) => ({
      ...prev,
      waypoints: prev.waypoints.map((item, i) => (i === index ? { ...item, name: value } : item)),
    }))
  }

  const addWaypoint = () => setForm((prev) => ({ ...prev, waypoints: [...prev.waypoints, { name: '' }] }))
  const removeWaypoint = (index: number) => setForm((prev) => ({ ...prev, waypoints: prev.waypoints.filter((_, i) => i !== index) }))

  const resetUploadState = () => {
    setUploadPreview('')
    setUploadError('')
    setUploadKind('')
    setAudioDebug(null)
    setLastAudioDebugText('')
  }

  const appendContextToFormData = (formData: FormData, intent: ReturnType<typeof detectQuestionIntent>) => {
    if (intent === 'travel') {
      formData.append('origin', form.origin)
      formData.append('destination', form.destination)
      formData.append('preferences', form.preferences)
      formData.append('travel_mode', form.travel_mode)
      formData.append('waypoint_order', String(form.waypoint_order))
      formData.append('waypoints_json', JSON.stringify(form.waypoints.filter((item) => item.name.trim()).map((item) => ({ name: item.name.trim() }))))
      return
    }

    formData.append('preferences', form.preferences)
    formData.append('travel_mode', form.travel_mode)
    formData.append('origin', form.origin)
    formData.append('destination', form.destination)
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
    if (uploadContext.file_kind === 'image') {
      setUploadPreview('图片已上传，已交由后端进行内容分析')
      setUploadError('')
      return
    }
    if (uploadContext.extracted_text) {
      setUploadPreview(uploadContext.extracted_text)
      setInput(uploadContext.extracted_text)
      setUploadError('')
    } else if (uploadContext.file_kind) {
      setUploadPreview(`${uploadContext.file_kind} 已接收，但未提取到可用文本`)
      setUploadError(uploadContext.extraction_error ? `解析错误：${uploadContext.extraction_error}` : '')
    }
  }

  const syncResponseState = (data: UnifiedChatResponse) => {
    setConversationId(data.conversation_id || '')

    const answerType = data.answer_type || 'general_chat'
    const travelPlan = normalizeTravelPlan(data.data?.travel_plan)
    const nearby = data.data?.nearby

    if (answerType === 'nearby_search') {
      setResult(null)
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
    } else if (answerType === 'travel_planning' && travelPlan) {
      setResult(travelPlan)
      setHistory(travelPlan.history || [])
      setMessages((prev) => [...prev, { role: 'assistant', content: data.final_answer || travelPlan.summary || '暂无结果' }])
    } else {
      setResult(null)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.final_answer || '暂无结果' }])
    }
  }

  const requestChat = async (questionText: string) => {
    const intent = detectQuestionIntent(questionText)

    const buildFormData = () => {
      const formData = new FormData()
      formData.append('question', questionText)
      if (intent !== 'nearby' && conversationId) formData.append('conversation_id', conversationId)
      if (upload) {
        if (upload.type.startsWith('audio/')) {
          formData.append('audio', upload)
        } else {
          formData.append('image', upload)
        }
      }
      appendContextToFormData(formData, intent)
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
    } finally {
      setLoading(false)
    }
  }

  const runPlan = async () => {
    if (!canPlan) return
    setLoading(true)
    setError('')

    try {
      const response = await fetch(apiUrl('/plan'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin: form.origin,
          destination: form.destination,
          preferences: form.preferences,
          travel_mode: form.travel_mode,
          conversation_id: conversationId || undefined,
          waypoints: form.waypoints.filter((item) => item.name.trim()).map((item) => ({ name: item.name.trim() })),
          waypoint_order: form.waypoint_order,
          request_source: 'sidebar',
        }),
      })

      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new Error(detail || `请求失败 ${response.status}`)
      }

      const data = normalizeTravelPlan(await response.json())
      if (!data) throw new Error('旅行规划结果格式无效')
      setResult(data)
      setConversationId(data.conversation_id || '')
      setHistory(data.history || [])
      setMessages((prev) => [...prev, { role: 'assistant', content: data.summary }])
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const applyHistory = (item: ConversationTurn) => {
    setInput(item.user_input)
    setMessages((prev) => [...prev, { role: 'assistant', content: item.assistant_output }])
  }

  const resetAll = () => {
    setMessages([])
    setResult(null)
    setHistory([])
    setConversationId('')
    setUpload(null)
    resetUploadState()
    localStorage.removeItem(CONVERSATION_KEY)
    localStorage.removeItem(HISTORY_KEY)
  }

  const quickActionButtons = useMemo(() => ([
    { label: '旅行规划', value: createQuickPrompt('travel') },
    { label: '周边推荐', value: createQuickPrompt('nearby') },
  ]), [])

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AI 出行 Agent</p>
          <h1>智能旅游规划工作台</h1>
          <p className="subtitle">统一支持旅行规划与周边推荐，行程中保留实时天气参考。</p>
        </div>
        <div className="topbar-actions">
          <span className="status-pill">{conversationId ? `会话 ${conversationId.slice(0, 8)}` : '新会话'}</span>
          <button className="ghost-button" onClick={resetAll}>清空会话</button>
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar left-panel">
          <section className="card">
            <div className="section-head">
              <h2>快捷指令</h2>
            </div>
            <div className="chip-row">
              {quickActionButtons.map((item) => (
                <ToolChip key={item.label} label={item.label} onClick={() => setInput(item.value)} />
              ))}
            </div>
          </section>

          <section className="card">
            <div className="section-head">
              <h2>行程偏好</h2>
            </div>
            <div className="field-list">
              <label>
                出发地
                <input placeholder="如：济南西站" value={form.origin} onChange={(e) => updateField('origin', e.target.value)} />
              </label>
              <label>
                目的地
                <input placeholder="如：北京" value={form.destination} onChange={(e) => updateField('destination', e.target.value)} />
              </label>
              <label>
                偏好
                <textarea
                  rows={3}
                  placeholder="如：三天两晚、预算3000、亲子出行、沿途想看博物馆和公园"
                  value={form.preferences}
                  onChange={(e) => updateField('preferences', e.target.value)}
                />
              </label>
              <label>
                出行方式
                <select value={form.travel_mode} onChange={(e) => updateField('travel_mode', e.target.value as PlanForm['travel_mode'])}>
                  <option value="driving">驾车</option>
                  <option value="walking">步行</option>
                  <option value="transit">公交</option>
                  <option value="bicycling">骑行</option>
                </select>
              </label>
              <label className="checkbox-row">
                <input type="checkbox" checked={form.waypoint_order} onChange={(e) => updateField('waypoint_order', e.target.checked)} />
                <span>启用途经点智能排序</span>
              </label>
            </div>

            <div className="waypoints-block">
              <div className="section-head compact-head">
                <h3>途经点</h3>
                <button type="button" className="ghost-button small" onClick={addWaypoint}>添加</button>
              </div>
              {form.waypoints.length === 0 ? <p className="muted">可留空，或在聊天里输入“途经泰安、德州”自动识别</p> : null}
              {form.waypoints.map((item, index) => (
                <div key={index} className="waypoint-row">
                  <input value={item.name} onChange={(e) => updateWaypoint(index, e.target.value)} placeholder={`途经点 ${index + 1}`} />
                  <button type="button" className="ghost-button small" onClick={() => removeWaypoint(index)}>删除</button>
                </div>
              ))}
            </div>

            <button className="primary-button full-width" onClick={runPlan} disabled={!canPlan}>
              {loading ? '规划中...' : '生成路线方案'}
            </button>
          </section>

          <section className="card history-card">
            <div className="section-head">
              <h2>历史记录</h2>
              <span className="muted">{history.length} 条</span>
            </div>
            <div className="history-list">
              {history.length === 0 ? (
                <p className="empty-state">暂无历史记录</p>
              ) : history.map((item, index) => (
                <button key={`${item.user_input}-${index}`} className="history-item" onClick={() => applyHistory(item)}>
                  <strong>{item.user_input}</strong>
                  <span>{item.assistant_output}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="center-panel card chat-card">
          <div className="section-head">
            <h2>对话区</h2>
            <span className="muted">支持多轮输入与多模态</span>
          </div>

          <div className="chat-stream">
            {messages.length === 0 ? (
              <div className="empty-chat">
                <h3>开始提问吧</h3>
                <p>你可以直接询问附近酒店/餐厅，或输入出行需求生成完整路线方案。</p>
              </div>
            ) : messages.map((message, index) => <MessageBubble key={`${message.role}-${index}`} message={message} />)}
          </div>

          <div className="composer">
            <textarea
              rows={4}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入旅行规划或周边推荐需求"
            />

            <div className="composer-actions">
              <label className="file-input">
                <input
                  type="file"
                  accept="image/*,.pdf,.txt,.md,.csv,.log,.json,audio/*"
                  onChange={async (e) => {
                    const selected = e.target.files?.[0] || null
                    setUpload(selected)
                    resetUploadState()
                    if (selected) {
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
                          // ignore local preview failure and fallback to server extraction
                        }
                      }
                    } else {
                      setUploadKind('')
                    }
                  }}
                />
                <span>{upload ? `已选${uploadKind === 'audio' ? '语音文件' : uploadKind === 'image' ? '图片文件' : '文件'}：${upload.name}` : '上传图片、文档、PDF 或语音文件后将根据内容回答'}</span>
              </label>

              {import.meta.env.DEV && uploadKind === 'audio' && (uploadPreview || lastAudioDebugText) ? (
                <div className="debug-box">
                  <strong>语音调试信息</strong>
                  <pre>{uploadPreview || lastAudioDebugText}</pre>
                </div>
              ) : null}
              {uploadKind === 'image' && uploadPreview ? <p className="muted">图片识别结果：{uploadPreview}</p> : null}
              {uploadKind !== 'audio' && uploadKind !== 'image' && uploadPreview ? <p className="muted">识别内容预览：{uploadPreview}</p> : null}
              {uploadError ? <p className="error-text">{uploadError}</p> : null}

              <div className="action-row">
                <button
                  className="ghost-button"
                  onClick={() => {
                    setInput('')
                    setUpload(null)
                    resetUploadState()
                    setAudioDebug(null)
                    setLastAudioDebugText('')
                  }}
                  disabled={loading}
                >
                  清空输入
                </button>
                <button className="primary-button" onClick={() => runChat()} disabled={!canSend}>
                  {loading ? '思考中...' : '发送消息'}
                </button>
              </div>
            </div>

            {error ? <p className="error-text">{error}</p> : null}
          </div>
        </section>

        <aside className="sidebar right-panel">
          <section className="card route-card">
            <div className="section-head">
              <h2>结果面板</h2>
              <span className="muted">统一结果展示</span>
            </div>

            {result ? <PlanCard plan={result} /> : <div className="empty-state">还没有生成结果，先在左侧提交出行天数、预算、目的地和偏好。</div>}
          </section>
        </aside>
      </main>
    </div>
  )
}
