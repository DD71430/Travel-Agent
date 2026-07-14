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

function getWaypointNames(rawRoute?: Record<string, unknown>) {
  const details = rawRoute?.waypoint_details
  if (!Array.isArray(details)) return []
  return details
    .map((item) => {
      if (!item || typeof item !== 'object') return ''
      const name = (item as Record<string, unknown>).name
      return typeof name === 'string' ? name.trim() : ''
    })
    .filter(Boolean)
}

export function buildTravelPlanChatSummary(plan: TravelPlanSummaryInput) {
  const title = (plan.route_title || '旅行').replace(/\s*旅游规划方案\s*$/, '').trim()
  const duration = plan.duration_days ? `${plan.duration_days} 天` : ''
  const waypoints = getWaypointNames(plan.raw_route)
  const waypointText = waypoints.length ? `，包含${waypoints.slice(0, 2).join('、')}停留` : ''
  const routeText = [title, duration].filter(Boolean).join(' ')
  return `已生成${routeText || '旅行'}方案${waypointText}，每日天气和交通安排已更新到结果面板。`
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
