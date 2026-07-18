import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { getUploadContextPreview } from '../src/chatUi.js'
import { ChatComposer } from '../src/components/ChatComposer.js'
import { AnswerResult } from '../src/components/AnswerResult.js'
import { MessageBubble } from '../src/components/MessageBubble.js'
import { PlanCard } from '../src/components/PlanCard.js'
import { WeatherCard } from '../src/components/WeatherCard.js'

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message)
}

const imagePreview = getUploadContextPreview({
  file_kind: 'image',
  extracted_text: '',
  extraction_error: 'image_content_not_parsed',
})

assert(imagePreview.preview.includes('暂未解析图片内容'), 'image upload preview must be honest about unsupported recognition')
assert(!imagePreview.preview.includes('内容分析'), 'image upload preview must not imply image analysis')

const messageMarkup = renderToStaticMarkup(createElement(MessageBubble, {
  message: { role: 'assistant', content: '已生成旅行方案' },
}))
assert(messageMarkup.includes('Agent'), 'message bubble should render the assistant role')
assert(messageMarkup.includes('已生成旅行方案'), 'message bubble should render message content')

const composerMarkup = renderToStaticMarkup(createElement(ChatComposer, {
  input: '',
  loading: false,
  canSend: true,
  uploadName: '图片 / 文档 / 语音',
  uploadKind: '',
  uploadPreview: '',
  uploadError: '',
  error: '',
  lastAudioDebugText: '',
  onInputChange: () => undefined,
  onFileChange: () => undefined,
  onClear: () => undefined,
  onSend: () => undefined,
}))
assert(composerMarkup.includes('图片 / 文档 / 语音'), 'composer should render the upload affordance')
assert(composerMarkup.includes('发送'), 'composer should render a send button')

const planMarkup = renderToStaticMarkup(createElement(PlanCard, {
  plan: {
    conversation_id: 'test-plan',
    intent: 'travel_planning',
    scenario: 'travel_tourism',
    summary: '杭州三天两晚旅行方案',
    route_title: '济南 → 杭州旅游规划方案',
    duration_days: 3,
    data_source: 'fallback',
    route_error: 'Geocode failed: Unable to resolve waypoint: 徐州并停留 via region_center',
    daily_itinerary: [],
    raw_route: {
      location_debug: { reason: 'geocode_failed' },
    },
    response_meta: { memory: { backend: 'memory_fallback', connected: false } },
  },
}))
assert(planMarkup.includes('济南 → 杭州'), 'plan card should render the route title')
assert(planMarkup.includes('兜底规划'), 'plan card should keep fallback status visible')
assert(!planMarkup.includes('fallback(fallback)'), 'plan card should not expose raw fallback labels')
assert(planMarkup.includes('地址解析失败'), 'plan card should surface geocode fallback reason')

const inferredWeatherBadgeMarkup = renderToStaticMarkup(createElement(PlanCard, {
  plan: {
    conversation_id: 'weather-badge-plan',
    intent: 'travel_planning',
    scenario: 'travel_tourism',
    summary: '济南到杭州三天两晚旅行方案',
    route_title: '济南 → 杭州旅游规划方案',
    duration_days: 3,
    data_source: 'tencent_maps',
    daily_itinerary: [{
      day: 1,
      title: '徐州停留',
      stage: 'route',
      anchor_city: '徐州',
      route_segment: '济南 → 徐州',
      weather_badge: '天气参考',
      weather_summary: '',
      morning: '上午抵达徐州',
      afternoon: '下午游览云龙湖',
      evening: '晚间休息',
      notes: [],
    }],
    raw_route: {
      weather_context: {
        data_source: 'tencent_maps',
        daily_weather: [{
          day: 1,
          city: '徐州',
          weather: '阴',
          temperature: '23-29℃',
          outdoor_suitability: 'good',
          indoor_priority: false,
          data_source: 'tencent_maps',
          weather_tags: ['weather_normal'],
        }],
      },
    },
    response_meta: { memory: { backend: 'redis', connected: true } },
  },
}))
assert(inferredWeatherBadgeMarkup.includes('阴天'), 'plan card should infer cloudy weather badge from resolved weather text')
assert(!inferredWeatherBadgeMarkup.includes('室外适合'), 'plan card should prefer weather condition labels over suitability labels')

const weatherMarkup = renderToStaticMarkup(createElement(WeatherCard, {
  weather: {
    city: '杭州',
    connected: false,
    data_source: 'fallback',
    fallback_reason: 'missing_key',
    summary: '腾讯天气未接通',
    daily_weather: [],
  },
}))
assert(weatherMarkup.includes('未接通 fallback'), 'weather card should keep fallback status visible')
assert(weatherMarkup.includes('杭州'), 'weather card should render the city')

const inlinePlanMarkup = renderToStaticMarkup(createElement(AnswerResult, {
  plan: {
    conversation_id: 'inline-plan',
    intent: 'travel_planning',
    scenario: 'travel_tourism',
    summary: '杭州三天两晚旅行方案',
    route_title: '济南 → 杭州旅游规划方案',
    duration_days: 3,
    data_source: 'fallback',
    daily_itinerary: [],
    response_meta: { memory: { backend: 'memory_fallback', connected: false } },
  },
  weather: null,
}))
assert(inlinePlanMarkup.includes('旅行 Agent 结果'), 'inline result should label structured travel output')
assert(inlinePlanMarkup.includes('济南 → 杭州'), 'inline result should render plan output in the answer flow')
