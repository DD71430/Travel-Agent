import { useEffect, useState } from 'react'
import { SidebarPanel, type SidebarHistoryEntry } from './SidebarPanel'
import { QUICK_ACTIONS, buildChatTextFields, buildTravelPlanChatSummary, createQuickActionDraft, getResponseResultKind } from './chatUi'
import { limitPlanDays, replacePlanResult } from './planDisplay'
import { findWeatherDayForPlanDay, formatWeatherDisplayLine, isFallbackWeatherForDisplay } from './weatherDisplay'

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

function getDataSourceLabel(value?: string) {
  if (!value) return 'unknown'
  if (value === 'tencent_maps') return '腾讯地图真实返回'
  if (value === 'weather_service') return '实时天气参考'
  if (value === 'poi_search') return '周边 POI 真实返回'
  return `fallback(${value})`
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

function formatHistoryTitle(text: string) {
  const match = text.match(/从?([^，。；,]+?)(?:自驾|驾车|开车|公交|公共交通|地铁|骑行|步行)?(?:到|去)([^，。；,]+?)(?:\d|三|两|一|，|,|。|$)/)
  if (match) return `${match[1].replace(/^从/, '').trim()} -> ${match[2].trim()}`
  return text.length > 18 ? `${text.slice(0, 18)}...` : text
}

function formatGeneratedAt(value?: string) {
  if (!value) return '本次会话'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '本次会话'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
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

function getWeatherTone(badge?: string | null, tags?: string[], isFallback = false) {
  const tagText = (tags || []).join(',')
  if (isFallback || badge === '天气待确认' || tagText.includes('weather_unconfirmed')) return 'fallback'
  if (badge === '雨天' || badge === '预警' || tagText.includes('rain')) return 'rain'
  if (badge === '高温' || badge === '晴热' || tagText.includes('heat') || tagText.includes('sun_exposure')) return 'heat'
  return 'normal'
}

function getMemoryStatusLabel(meta?: Record<string, unknown>) {
  const memory = isObject(meta?.memory) ? meta.memory : null
  if (!memory) return '未返回'
  if (memory.backend === 'redis' && memory.connected) return 'Redis 已连接'
  if (memory.backend === 'memory_fallback') return '使用内存 fallback'
  return String(memory.backend || '未知')
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

function getTransportModeLabel(value?: unknown, local = false) {
  const mode = typeof value === 'string' ? value : ''
  const intercityLabels: Record<string, string> = {
    driving: '自驾/驾车',
    high_speed_rail: '高铁/动车',
    train: '火车/铁路',
    flight: '飞机/航班',
    coach: '长途大巴',
    transit: '公共交通',
    unknown: '未指定',
  }
  const localLabels: Record<string, string> = {
    driving: '自驾/打车',
    taxi: '打车/网约车',
    transit: '市内公共交通',
    walking: '步行',
    bicycling: '骑行',
    mixed: '市内公共交通/打车',
    unknown: '未指定',
  }
  return (local ? localLabels : intercityLabels)[mode] || mode || '未指定'
}

function getProfileString(profile: Record<string, unknown> | null | undefined, key: string) {
  const value = profile?.[key]
  return typeof value === 'string' && value.trim() ? value : ''
}

function formatDayTransport(day: TripDayPlan) {
  const block = isObject(day.transport_block) ? day.transport_block : null
  const label = typeof block?.label === 'string' && block.label.trim() ? block.label : ''
  const summary = typeof block?.summary === 'string' && block.summary.trim() ? block.summary : ''
  if (summary) return summary
  if (label) return `${label}约${day.drive_time || '按实时班次'}`
  return day.drive_time || '按实时路况'
}

function PlanCard({ plan }: { plan: TravelPlanResponse }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'daily' | 'weather' | 'debug'>('overview')
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
  const weatherPlanSummary = isObject(routeDebug?.weather_plan_summary) ? routeDebug?.weather_plan_summary : null
  const dailyWeather = Array.isArray(weatherContext?.daily_weather) ? weatherContext?.daily_weather : []
  const waypointDetails = Array.isArray(routeDebug?.waypoint_details) ? routeDebug?.waypoint_details : []
  const mustVisitAttractions = Array.isArray(routeDebug?.must_visit_attractions) ? routeDebug?.must_visit_attractions : []
  const unscheduledWaypoints = Array.isArray(routeDebug?.unscheduled_waypoints) ? routeDebug?.unscheduled_waypoints : []
  const routeHighlights = plan.route_highlights || []
  const scenicTexts = plan.attraction_recommendations || []
  const weatherOverview = plan.weather_overview || weatherPlanSummary?.weather_overview || weatherContext?.summary || plan.weather_hint || '天气待确认'
  const weatherAdjustments = dedupeStrings(plan.weather_adjustments?.length ? plan.weather_adjustments : weatherPlanSummary?.weather_adjustments)
  const packingSummary = dedupeStrings(plan.packing_summary?.length ? plan.packing_summary : weatherPlanSummary?.packing_summary)
  const dailyWeatherBriefs = dedupeStrings(weatherPlanSummary?.daily_weather_briefs)
  const visibleDailyItinerary = limitPlanDays(plan.daily_itinerary, plan.duration_days)
  const memoryLabel = getMemoryStatusLabel(plan.response_meta)
  const sourceLabel = getDataSourceLabel(plan.data_source)
  const intercityMode = getProfileString(tripProfile, 'intercity_mode') || String(routeDebug?.request_debug?.travel_mode || '')
  const localMode = getProfileString(tripProfile, 'local_mode')
  const intercityLabel = getProfileString(tripProfile, 'intercity_label') || getTransportModeLabel(intercityMode)
  const localLabel = getProfileString(tripProfile, 'local_label') || (localMode ? getTransportModeLabel(localMode, true) : '')
  const transportDisplay = localLabel && localLabel !== intercityLabel ? `${intercityLabel} + ${localLabel}` : intercityLabel || '--'
  const weatherDebugDays = visibleDailyItinerary.map((day) => ({
    day: day.day,
    anchor_city: day.anchor_city,
    weather_badge: day.weather_badge,
    weather_summary: day.weather_summary,
    matched_weather_day: findWeatherDayForPlanDay(day, dailyWeather) || null,
  }))
  const generatedAt = getProfileString(routeDebug?.request_debug, 'generated_at') || routeDebug?.generated_at
  const overviewItems = [
    { label: '天数', value: `${plan.duration_days || '--'} 天` },
    { label: '交通方式', value: transportDisplay },
    { label: '总耗时', value: plan.route_total_duration || routeDebug?.best_option?.duration || '--' },
    { label: '总距离', value: plan.route_total_distance || routeDebug?.best_option?.distance || '--' },
  ]

  const renderDayCard = (day: TripDayPlan) => {
    const weatherDay = findWeatherDayForPlanDay(day, dailyWeather)
    const isFallbackWeather = isFallbackWeatherForDisplay(day, weatherDay, weatherContext?.data_source)
    const weatherTips = dedupeStrings(day.weather_tips?.length ? day.weather_tips : weatherDay?.weather_tips)
    const packingTips = dedupeStrings(day.packing_tips?.length ? day.packing_tips : weatherDay?.packing_tips)
    const badge = day.weather_badge || getWeatherBadge(weatherDay, isFallbackWeather)
    const tone = getWeatherTone(badge, day.weather_tags?.length ? day.weather_tags : weatherDay?.weather_tags, isFallbackWeather)
    const displayNotes = getDisplayNotes(day)
    const keyNotes = displayNotes.slice(0, 2)
    return (
      <article key={day.day} className="day-card">
        <div className="day-card-head">
          <strong>Day {day.day}</strong>
          <span>{day.anchor_city || '当天城市'} · {day.route_segment || '按当日景点顺序串联'}</span>
          <em>{getStageLabel(day.stage)}</em>
          <em className={`weather-stage-badge ${tone}`}>{badge}</em>
        </div>
        <div className={`weather-chip-row ${tone}`}>
          <strong>{badge}</strong>
          {isFallbackWeather ? (
            <>
              <span>{formatWeatherDisplayLine(day, weatherDay, true)}</span>
              <small>本日不做天气重排</small>
            </>
          ) : (
            <>
              <span>{formatWeatherDisplayLine(day, weatherDay, false)}</span>
              <small>{day.weather_summary || weatherDay?.strategy || '已用于行程排序'}</small>
            </>
          )}
        </div>
        {isFallbackWeather ? (
          <p className="fallback-equipment-line">备选装备：雨具 / 防晒 / 水杯</p>
        ) : (weatherTips.length || day.weather_adjustments?.length) ? (
          <div className="weather-tip-panel">
            <ul className="weather-tip-list">
              {dedupeStrings([...(day.weather_adjustments || []), ...weatherTips]).slice(0, 4).map((tip) => <li key={tip}>{tip}</li>)}
            </ul>
          </div>
        ) : null}
        {!isFallbackWeather && packingTips.length ? (
          <div className="packing-chip-row">
            {packingTips.slice(0, 8).map((tip) => <span key={tip}>{tip}</span>)}
          </div>
        ) : null}
        <div className="day-route-meta">
          <span>交通/转场：{formatDayTransport(day)}</span>
          <span>可游玩：{day.visit_time || '约半天至全天'}</span>
        </div>
        <div className="day-schedule">
          {[
            ['上午', day.morning],
            ['下午', day.afternoon],
            ['晚上', day.evening],
          ].map(([period, content]) => (
            <div key={period} className="schedule-row">
              <span>{period}</span>
              <p>{content}</p>
            </div>
          ))}
        </div>
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
        {keyNotes.length ? (
          <div className="note-row">
            {keyNotes.map((note) => <span key={note}>{note}</span>)}
          </div>
        ) : null}
        <details className="day-details">
          <summary>餐饮、住宿与完整调度说明</summary>
          {day.meals?.length ? <p><b>餐饮：</b>{dedupeStrings(day.meals).join(' ')}</p> : null}
          {day.hotel_hint ? <p><b>住宿：</b>{day.hotel_hint}</p> : null}
          {displayNotes.length ? (
            <div className="note-row">
              {displayNotes.map((note) => <span key={note}>{note}</span>)}
            </div>
          ) : null}
        </details>
      </article>
    )
  }

  return (
    <div className="plan-card">
      <div className="plan-hero">
        <div>
          <h3>{plan.route_title}</h3>
          <p>{plan.trip_overview || plan.summary}</p>
        </div>
        <div className="result-source">
          <span className="status-badge">{sourceLabel}</span>
          <time>生成于 {formatGeneratedAt(generatedAt)}</time>
        </div>
      </div>

      <div className="overview-strip">
        {overviewItems.map((item) => (
          <div key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      {plan.data_source && plan.data_source !== 'tencent_maps' ? (
        <div className="fallback-banner">当前为兜底规划，真实路线、营业时间和票务信息请以出行前查询为准。</div>
      ) : null}
      <div className={`weather-banner${weatherContext?.data_source === 'fallback' ? ' warning' : ' resolved'}`}>
        <strong>{weatherContext?.data_source === 'fallback' ? '天气待确认' : '天气已融入行程'}</strong>
        <span>{weatherContext?.data_source === 'fallback' ? '建议出行前查看实时天气；本行程保留室内/室外备选。' : weatherOverview}</span>
      </div>
      {unscheduledWaypoints.length ? (
        <div className="fallback-banner">未安排途经点/景点：{unscheduledWaypoints.join('、')}。建议延长停留或作为备选。</div>
      ) : null}

      <div className="result-tabs" role="tablist" aria-label="结果分区">
        {[
          ['overview', '总览'],
          ['daily', '每日行程'],
          ['weather', '天气与装备'],
          ['debug', '调试信息'],
        ].map(([key, label]) => (
          <button key={key} type="button" className={activeTab === key ? 'active' : ''} onClick={() => setActiveTab(key as typeof activeTab)}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' ? (
        <div className="tab-panel">
          <div className="plan-meta-grid">
            <div><span>行程类型</span><strong>{getTripTypeLabel(plan.trip_type, tripProfile?.stage_plan_mode)}</strong></div>
            <div><span>沿途/目的地</span><strong>{routeDays ?? 0} 天 / {destinationDays ?? 0} 天{bufferDays ? ` / 机动 ${bufferDays} 天` : ''}</strong></div>
            <div><span>出行方式</span><strong>{transportDisplay}</strong></div>
            <div><span>顺序模式</span><strong>{getWaypointOrderLabel(routeDebug?.waypoint_order_mode)}</strong></div>
            <div><span>途经点</span><strong>{waypointDetails.length ? waypointDetails.map((item) => item.name).join('、') : '--'}</strong></div>
            <div><span>必去景点</span><strong>{mustVisitAttractions.length ? mustVisitAttractions.join('、') : '--'}</strong></div>
          </div>
          <div className="highlight-strip">
            <div><span>路程拆分</span><strong>{plan.transportation_suggestion?.[0] || plan.trip_overview || '已按实际路程时间进行行程切分'}</strong></div>
            <div><span>天气融入</span><strong>{weatherOverview}</strong></div>
            <div><span>景点串联</span><strong>{routeHighlights[0]?.title || plan.scenic_route_highlights?.[0] || '已优先串联相邻景点并按游览节奏排序'}</strong></div>
          </div>
          <div className="plan-section">
            <h4>推荐景点</h4>
            <ul>{scenicTexts.slice(0, 6).map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
          <div className="plan-footer-grid">
            <div className="plan-section">
              <h4>交通建议</h4>
              <ul>{(plan.transportation_suggestion || []).slice(0, 4).map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <div className="plan-section">
              <h4>旅行贴士</h4>
              <ul>{(plan.travel_tips || []).slice(0, 4).map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          </div>
        </div>
      ) : null}

      {activeTab === 'daily' ? (
        <div className="tab-panel itinerary-list">
          {visibleDailyItinerary.map(renderDayCard)}
        </div>
      ) : null}

      {activeTab === 'weather' ? (
        <div className="tab-panel">
          <div className="plan-section">
            <h4>天气总览</h4>
            <p>{weatherOverview}</p>
          </div>
          {weatherAdjustments.length ? (
            <div className="plan-section">
              <h4>行程调整</h4>
              <ul>{weatherAdjustments.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}
          {dailyWeatherBriefs.length ? (
            <div className="plan-section">
              <h4>每日天气</h4>
              <ul>{dailyWeatherBriefs.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}
          {packingSummary.length ? (
            <div className="plan-section">
              <h4>装备建议</h4>
              <div className="packing-chip-row">{packingSummary.map((item) => <span key={item}>{item}</span>)}</div>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeTab === 'debug' ? (
        <div className="tab-panel">
          <details className="debug-details">
            <summary>调试信息</summary>
            <div className="debug-grid">
              <div><span>记忆状态</span><strong>{memoryLabel}</strong></div>
              <div><span>天气来源</span><strong>{weatherContext?.data_source || '--'}</strong></div>
              <div><span>路线来源</span><strong>{plan.data_source || '--'}</strong></div>
              <div><span>置信度</span><strong>{plan.confidence || '--'}</strong></div>
            </div>
            <pre>{JSON.stringify({ memory: plan.response_meta?.memory, request_debug: routeDebug?.request_debug, weather_context: weatherContext?.request_debug, weather_debug_days: weatherDebugDays }, null, 2)}</pre>
          </details>
        </div>
      ) : null}
    </div>
  )
}

function WeatherCard({ weather }: { weather: WeatherQueryData }) {
  const connected = Boolean(weather.connected)
  const dailyWeather = Array.isArray(weather.daily_weather) ? weather.daily_weather : []
  const weatherTips = dedupeStrings(weather.weather_tips)
  const packingTips = dedupeStrings(weather.packing_tips)
  const statusTone = connected ? 'connected' : 'fallback'
  return (
    <div className="weather-card">
      <div className="plan-hero">
        <div>
          <h3>天气查询 / 天气接口诊断</h3>
          <p>{weather.summary || '暂未获取天气摘要'}</p>
        </div>
        <span className={`status-badge weather-status ${statusTone}`}>{connected ? '腾讯天气已接通' : '未接通 fallback'}</span>
      </div>

      <div className="plan-meta-grid">
        <div><span>城市</span><strong>{weather.city || '--'}</strong></div>
        <div><span>adcode</span><strong>{weather.adcode || '--'}</strong></div>
        <div><span>数据来源</span><strong>{weather.data_source || '--'}</strong></div>
        <div><span>失败原因</span><strong>{weather.fallback_reason || '--'}</strong></div>
      </div>

      {dailyWeather.length ? (
        <div className="weather-daily-list">
          {dailyWeather.map((day) => {
            const tone = getWeatherTone(undefined, day.weather_tags, day.data_source !== 'tencent_maps')
            return (
              <div key={`${day.day}-${day.city}`} className={`weather-day-row ${tone}`}>
                <strong>第{day.day || '?'}天</strong>
                <span>{day.city || weather.city} · {day.weather || '天气待确认'} · {day.temperature || '温度待确认'}</span>
                <small>{day.strategy || day.fallback_reason || '按实时天气微调'}</small>
              </div>
            )
          })}
        </div>
      ) : null}

      {weatherTips.length ? (
        <div className="plan-section">
          <h4>天气建议</h4>
          <ul>{weatherTips.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ) : null}

      {packingTips.length ? (
        <div className="plan-section">
          <h4>装备建议</h4>
          <div className="packing-chip-row">{packingTips.map((item) => <span key={item}>{item}</span>)}</div>
        </div>
      ) : null}

      <details className="debug-details">
        <summary>调试信息</summary>
        <pre>{JSON.stringify({ debug: weather.debug, memory: weather.response_meta?.memory }, null, 2)}</pre>
      </details>
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
  const [mobileView, setMobileView] = useState<'chat' | 'result'>('chat')

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
      setMobileView('result')
    } else if (resultKind === 'weather' && weather) {
      setResult(null)
      setWeatherResult({ ...weather, response_meta: data.meta })
      setMessages((prev) => [...prev, { role: 'assistant', content: data.final_answer || weather.summary || '暂无天气结果' }])
      setMobileView('result')
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
    setMobileView('chat')
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

      <div className="mobile-view-switch" role="group" aria-label="移动端工作区切换">
        <button type="button" className={mobileView === 'chat' ? 'active' : ''} onClick={() => setMobileView('chat')}>对话</button>
        <button type="button" className={mobileView === 'result' ? 'active' : ''} onClick={() => setMobileView('result')}>结果</button>
      </div>

      {sidebarOpen ? <button type="button" className="sidebar-scrim" aria-label="关闭历史侧栏" onClick={() => setSidebarOpen(false)} /> : null}

      <main className="workspace">
        <aside id="workspace-sidebar" className={`left-panel${sidebarOpen ? ' open' : ''}`}>
          <SidebarPanel
            quickActions={QUICK_ACTIONS}
            historyEntries={historyEntries}
            memoryLabel={memoryLabel}
            memoryConnected={Boolean(memoryStatus?.connected)}
            onSelectPrompt={(action) => {
              const draft = createQuickActionDraft(action)
              setInput(draft.input)
              setMobileView('chat')
              setSidebarOpen(false)
            }}
            onSelectHistory={selectHistoryEntry}
            onNewConversation={startNewConversation}
            onClose={() => setSidebarOpen(false)}
          />
        </aside>

        <section className={`center-panel chat-card${mobileView === 'chat' ? '' : ' mobile-hidden'}`}>
          <div className="section-head">
            <h2>对话区</h2>
            <span className="muted">唯一需求入口 · 支持文件与多轮会话</span>
          </div>

          <div className="chat-stream">
            {messages.length === 0 ? (
              <div className="empty-chat">
                <h3>开始提问吧</h3>
                <p>请直接写明出发地、目的地、天数、交通方式、途经城市和游览偏好。</p>
              </div>
            ) : messages.map((message, index) => <MessageBubble key={`${message.role}-${index}`} message={message} />)}
            {loading ? <div className="message assistant loading-message" role="status"><span className="message-role">Agent</span><p>正在分析路线、天气与交通安排…</p></div> : null}
          </div>

          <div className="composer">
            <textarea
              rows={3}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="例如：从济南到杭州三天两晚，乘高铁，途经徐州一天，偏好博物馆和经典景点…"
            />

            <div className="composer-actions">
              <div className="composer-toolbar">
                <div className="composer-tools">
                  <label className="icon-button file-input" title="上传图片、文档、PDF 或语音" aria-label="上传图片、文档、PDF 或语音">
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
                              // Server extraction remains available when local preview fails.
                            }
                          }
                        } else {
                          setUploadKind('')
                        }
                      }}
                    />
                    <span aria-hidden="true">↑</span>
                  </label>
                  <span className="upload-name">{upload ? upload.name : '图片 / 文档 / 语音'}</span>
                </div>
                <div className="composer-commands">
                  <button type="button" className="icon-button" title="清空输入" aria-label="清空输入" onClick={clearComposer} disabled={loading}>×</button>
                  <button type="button" className="primary-button send-button" onClick={() => runChat()} disabled={!canSend}>
                    {loading ? '发送中…' : '发送'}
                  </button>
                </div>
              </div>

              {import.meta.env.DEV && uploadKind === 'audio' && (uploadPreview || lastAudioDebugText) ? (
                <div className="debug-box">
                  <strong>语音调试信息</strong>
                  <pre>{uploadPreview || lastAudioDebugText}</pre>
                </div>
              ) : null}
              {uploadKind === 'image' && uploadPreview ? <p className="muted">图片识别结果：{uploadPreview}</p> : null}
              {uploadKind !== 'audio' && uploadKind !== 'image' && uploadPreview ? <p className="muted">识别内容预览：{uploadPreview}</p> : null}
              {uploadError ? <p className="error-text">{uploadError}</p> : null}
            </div>

            {error ? <p className="error-text">{error}</p> : null}
          </div>
        </section>

        <aside className={`right-panel${mobileView === 'result' ? '' : ' mobile-hidden'}`}>
          <section className="route-card">
            <div className="section-head">
              <h2>结果面板</h2>
              <span className="muted">路线、天气与交通统一展示</span>
            </div>

            {weatherResult ? (
              <WeatherCard weather={weatherResult} />
            ) : result ? (
              <PlanCard plan={result} />
            ) : (
              <div className="empty-state result-empty">还没有结果。在对话区输入完整旅行需求，或直接询问“未来三天杭州天气”。</div>
            )}
          </section>
        </aside>
      </main>
    </div>
  )
}
