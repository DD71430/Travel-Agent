export type QuickActionId = 'travel' | 'nearby' | 'weather'

export type QuickAction = {
  id: QuickActionId
  label: string
  prompt: string
}

export type ChatTextFieldInput = {
  question: string
  conversationId?: string
}

export type TravelPlanSummaryInput = {
  route_title?: string
  duration_days?: number
  raw_route?: Record<string, unknown>
  weather_overview?: string
  weather_hint?: string
  daily_itinerary?: Array<{
    day?: number
    title?: string
    anchor_city?: string | null
    route_segment?: string | null
    weather_summary?: string
    weather_badge?: string | null
    morning?: string
    afternoon?: string
    evening?: string
    attractions?: Array<{ name?: string }>
  }>
}

export type UploadPreviewInput = {
  file_kind?: string
  extracted_text?: string
  extraction_error?: string
}

export type UploadPreviewResult = {
  preview: string
  error: string
  shouldUseExtractedText: boolean
}

export const QUICK_ACTIONS: QuickAction[] = [
  {
    id: 'travel',
    label: '旅行规划',
    prompt: '帮我规划一个从济南到杭州三天两晚的旅行路线，乘坐高铁，途经徐州并停留一天，偏好经典景点和合理游览节奏。',
  },
  {
    id: 'nearby',
    label: '周边推荐',
    prompt: '推荐北京故宫附近交通方便的酒店、本地餐厅和适合步行串联的景点。',
  },
  {
    id: 'weather',
    label: '天气查询',
    prompt: '未来三天杭州天气怎么样？请按天列出天气、温度和出行建议。',
  },
]

export function buildChatTextFields({ question, conversationId }: ChatTextFieldInput): Array<[string, string]> {
  const fields: Array<[string, string]> = [['question', question]]
  if (conversationId) fields.push(['conversation_id', conversationId])
  return fields
}

export function createQuickActionDraft(action: QuickAction) {
  return {
    input: action.prompt,
    shouldSubmit: false as const,
  }
}

export function getResponseResultKind(
  answerType: string,
  availability: { hasWeather: boolean; hasTravelPlan: boolean },
): 'travel' | 'weather' | 'nearby' | 'chat' {
  if (answerType === 'travel_planning' && availability.hasTravelPlan) return 'travel'
  if (answerType === 'weather_query' && availability.hasWeather) return 'weather'
  if (answerType === 'nearby_search') return 'nearby'
  return 'chat'
}

export function getUploadContextPreview(uploadContext: UploadPreviewInput): UploadPreviewResult {
  const extractedText = String(uploadContext.extracted_text || '').trim()
  const extractionError = String(uploadContext.extraction_error || '').trim()

  if (uploadContext.file_kind === 'image') {
    return {
      preview: '图片已上传，当前版本暂未解析图片内容，请补充文字需求。',
      error: '',
      shouldUseExtractedText: false,
    }
  }

  if (extractedText) {
    return {
      preview: extractedText,
      error: '',
      shouldUseExtractedText: true,
    }
  }

  if (uploadContext.file_kind) {
    return {
      preview: `${uploadContext.file_kind} 已接收，但未提取到可用文本`,
      error: extractionError ? `解析错误：${extractionError}` : '',
      shouldUseExtractedText: false,
    }
  }

  return {
    preview: '',
    error: extractionError,
    shouldUseExtractedText: false,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function getStringName(value: unknown) {
  if (!isRecord(value)) return ''
  const name = value.name
  return typeof name === 'string' ? name.trim() : ''
}

function dedupeStrings(items: string[]) {
  const result: string[] = []
  for (const item of items) {
    const cleaned = item.trim()
    if (cleaned && !result.includes(cleaned)) result.push(cleaned)
  }
  return result
}

function getWaypointNames(rawRoute?: Record<string, unknown>) {
  return dedupeStrings(
    ['waypoint_details', 'route_stops']
      .flatMap((key) => {
        const value = rawRoute?.[key]
        return Array.isArray(value) ? value.map(getStringName) : []
      }),
  )
}

function getWeatherContext(rawRoute?: Record<string, unknown>) {
  const context = rawRoute?.weather_context
  return isRecord(context) ? context : null
}

function getDailyWeather(rawRoute?: Record<string, unknown>) {
  const context = getWeatherContext(rawRoute)
  const dailyWeather = context?.daily_weather
  return Array.isArray(dailyWeather) ? dailyWeather.filter(isRecord) : []
}

function normalizeCity(value?: string | null) {
  return (value || '').replace(/市/g, '').trim()
}

function findWeatherForDay(
  day: NonNullable<TravelPlanSummaryInput['daily_itinerary']>[number],
  dailyWeather: Record<string, unknown>[],
) {
  const dayNumber = Number(day.day || 0)
  const anchor = normalizeCity(day.anchor_city)
  return dailyWeather.find((item) => {
    const itemDay = Number(item.day || 0)
    const city = normalizeCity(typeof item.city === 'string' ? item.city : '')
    return itemDay === dayNumber && (!anchor || !city || city === anchor)
  })
}

function formatWeatherItem(item?: Record<string, unknown> | null) {
  if (!item) return ''
  const weather = typeof item.weather === 'string' ? item.weather.trim() : ''
  if (!weather || weather.includes('天气待确认')) return ''
  const city = typeof item.city === 'string' ? item.city.trim() : ''
  const temperature = typeof item.temperature === 'string' ? item.temperature.trim() : ''
  return [city, weather, temperature].filter(Boolean).join(' ')
}

function buildWeatherSummaryLine(plan: TravelPlanSummaryInput) {
  const context = getWeatherContext(plan.raw_route)
  const dailyWeather = getDailyWeather(plan.raw_route)
  const weatherItems = dailyWeather.map(formatWeatherItem).filter(Boolean).slice(0, 3)
  if (context?.data_source === 'tencent_maps' && weatherItems.length) {
    return `天气已查询：${weatherItems.join('；')}。`
  }
  const fallbackText = plan.weather_overview || plan.weather_hint || (typeof context?.summary === 'string' ? context.summary : '')
  if (fallbackText) return `天气待确认：${fallbackText}`
  return ''
}

function getDayAttractions(day: NonNullable<TravelPlanSummaryInput['daily_itinerary']>[number]) {
  return dedupeStrings((day.attractions || []).map((item) => item.name || '')).slice(0, 3)
}

function buildDaySummaryLine(
  day: NonNullable<TravelPlanSummaryInput['daily_itinerary']>[number],
  dailyWeather: Record<string, unknown>[],
) {
  const dayLabel = day.day ? `Day ${day.day}` : '当天'
  const anchor = day.anchor_city ? ` ${day.anchor_city}` : ''
  const names = getDayAttractions(day)
  const attractions = names.length ? names.join('、') : '抵达、休整或自由活动'
  const weather = formatWeatherItem(findWeatherForDay(day, dailyWeather))
  return `${dayLabel}${anchor}：${attractions}${weather ? `；天气：${weather}` : ''}。`
}

export function buildTravelPlanChatSummary(plan: TravelPlanSummaryInput) {
  const title = (plan.route_title || '旅行').replace(/\s*旅游规划方案\s*$/, '').trim()
  const duration = plan.duration_days ? `${plan.duration_days} 天` : ''
  const waypoints = getWaypointNames(plan.raw_route)
  const waypointText = waypoints.length ? `，包含${waypoints.slice(0, 2).join('、')}停留` : ''
  const routeText = [title, duration].filter(Boolean).join(' ')
  const lines = [`已生成${routeText || '旅行'}方案${waypointText}。`]
  const weatherLine = buildWeatherSummaryLine(plan)
  if (weatherLine) lines.push(weatherLine)
  const dailyWeather = getDailyWeather(plan.raw_route)
  for (const day of (plan.daily_itinerary || []).slice(0, 4)) {
    lines.push(buildDaySummaryLine(day, dailyWeather))
  }
  return lines.join('\n')
}

export function formatHistoryTime(value?: string) {
  if (!value) return ''
  const numeric = Number(value)
  const date = Number.isFinite(numeric) && numeric > 0
    ? new Date(numeric * (numeric < 10_000_000_000 ? 1000 : 1))
    : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
