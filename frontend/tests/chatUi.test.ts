import {
  QUICK_ACTIONS,
  buildChatTextFields,
  buildTravelPlanChatSummary,
  createQuickActionDraft,
  getResponseResultKind,
} from '../src/chatUi.js'

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message)
}

const fields = buildChatTextFields({
  question: '帮我规划从济南到杭州三天两晚的高铁旅行',
  conversationId: 'conversation-123',
})
const fieldNames = fields.map(([name]) => name)
const forbiddenFields = ['origin', 'destination', 'preferences', 'travel_mode', 'waypoint_order', 'waypoints_json']

assert(fieldNames.join(',') === 'question,conversation_id', 'chat text fields should only contain the question and conversation id')
assert(forbiddenFields.every((name) => !fieldNames.includes(name)), 'chat requests must not contain legacy trip form fields')

const travelAction = QUICK_ACTIONS.find((item) => item.id === 'travel')
assert(Boolean(travelAction), 'the sidebar should expose a travel planning quick action')
assert(QUICK_ACTIONS.some((item) => item.id === 'nearby'), 'the sidebar should expose a nearby search quick action')
assert(QUICK_ACTIONS.some((item) => item.id === 'weather'), 'the sidebar should expose a weather query quick action')

const travelDraft = createQuickActionDraft(travelAction!)
assert(travelDraft.shouldSubmit === false, 'a quick action should only fill the composer and never submit automatically')
assert(/从.+到.+/.test(travelDraft.input), 'the travel prompt should include an origin and destination')
assert(/三天|3天/.test(travelDraft.input), 'the travel prompt should include trip duration')
assert(/高铁|驾车|飞机|公共交通/.test(travelDraft.input), 'the travel prompt should include a transport mode')
assert(/经典|偏好|博物馆|节奏/.test(travelDraft.input), 'the travel prompt should include a clear preference')

const summary = buildTravelPlanChatSummary({
  route_title: '济南 → 杭州旅游规划方案',
  duration_days: 3,
  raw_route: {
    waypoint_details: [{ name: '徐州' }],
    weather_context: {
      data_source: 'tencent_maps',
      daily_weather: [
        { day: 1, city: '徐州', weather: '多云', temperature: '24-31℃' },
        { day: 2, city: '杭州', weather: '阵雨', temperature: '25-32℃' },
      ],
    },
  },
  daily_itinerary: [
    { day: 1, title: '第1天', anchor_city: '徐州', morning: '', afternoon: '', evening: '', attractions: [{ name: '徐州博物馆' }, { name: '云龙湖风景区' }] },
    { day: 2, title: '第2天', anchor_city: '杭州', morning: '', afternoon: '', evening: '', attractions: [{ name: '杭州博物馆' }] },
    { day: 3, title: '第3天', anchor_city: '杭州', morning: '', afternoon: '', evening: '', attractions: [{ name: '西湖风景名胜区' }, { name: '灵隐寺' }] },
  ],
  weather_overview: '未来两天有阵雨，已融入行程。',
})

assert(summary.includes('济南 → 杭州'), 'the travel chat summary should retain the route name')
assert(summary.includes('3 天'), 'the travel chat summary should retain the trip duration')
assert(summary.includes('徐州'), 'the travel chat summary should mention scheduled waypoints')
assert(summary.includes('徐州博物馆'), 'the travel chat summary should show concrete day attractions')
assert(summary.includes('西湖风景名胜区'), 'the travel chat summary should include destination attractions')
assert(summary.includes('天气已查询'), 'the travel chat summary should state when weather was queried')
assert(summary.includes('阵雨'), 'the travel chat summary should surface daily weather')
assert(!summary.includes('结果面板'), 'the travel chat summary should not hide the answer behind the result panel')
assert(!summary.includes('上午：'), 'the travel chat summary must not duplicate the full itinerary')

assert(
  getResponseResultKind('weather_query', { hasWeather: true, hasTravelPlan: false }) === 'weather',
  'a weather query response should enter the weather result view',
)
assert(
  getResponseResultKind('travel_planning', { hasWeather: false, hasTravelPlan: true }) === 'travel',
  'a travel planning response should enter the travel result view',
)
