import {
  compactWeatherItems,
  findWeatherDayForPlanDay,
  formatWeatherDisplayLine,
  isFallbackWeatherForDisplay,
} from '../src/weatherDisplay.js'

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message)
}

const planDay = {
  day: 1,
  anchor_city: '徐州',
  weather_badge: '雨天',
  weather_summary: '第1天徐州：晴天转小雨，26-34℃；带伞/雨衣并注意防滑。',
}

const fallbackContextDay = {
  day: 1,
  city: '徐州',
  weather: '天气待确认',
  temperature: '温度待确认',
  data_source: 'fallback',
}

assert(
  isFallbackWeatherForDisplay(planDay, fallbackContextDay, 'mixed') === false,
  'resolved itinerary weather should not be displayed as fallback',
)
assert(
  formatWeatherDisplayLine(planDay, fallbackContextDay, false).includes('第1天徐州'),
  'resolved itinerary summary should be used when context day is fallback',
)

const matched = findWeatherDayForPlanDay(planDay, [
  { day: 2, city: '杭州', weather: '多云', data_source: 'tencent_maps' },
  { day: 1, city: '徐州市', weather: '晴天转小雨', data_source: 'tencent_maps' },
])

assert(matched?.city === '徐州市', 'weather should be matched by day and normalized anchor city')

const wrongCityMatch = findWeatherDayForPlanDay(planDay, [
  { day: 1, city: '济南', weather: '晴', data_source: 'tencent_maps' },
  { day: 2, city: '徐州', weather: '小雨', data_source: 'tencent_maps' },
])

assert(wrongCityMatch === undefined, 'weather from another city or another day must not be attached to a plan day')
const unmatchedPlanDay = {
  ...planDay,
  weather_badge: '天气待确认',
  weather_summary: '第1天徐州天气待确认。',
}
assert(
  isFallbackWeatherForDisplay(unmatchedPlanDay, wrongCityMatch, 'tencent_maps') === true,
  'a missing per-day weather match must stay fallback even when the overall context uses Tencent Maps',
)

const compactedWeatherItems = compactWeatherItems(['雨天', '雨天', '高温', '高温', '防滑鞋'], 3)
assert(
  compactedWeatherItems.join(',') === '雨天,高温,防滑鞋',
  'daily weather display items should be unique and capped',
)
