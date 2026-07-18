export type WeatherDisplayDay = {
  day?: number
  city?: string
  weather?: string
  temperature?: string
  strategy?: string
  weather_tips?: string[]
  packing_tips?: string[]
  weather_tags?: string[]
  data_source?: string
  fallback_reason?: string | null
}

export type WeatherDisplayPlanDay = {
  day: number
  anchor_city?: string | null
  weather_badge?: string | null
  weather_summary?: string
}

export function normalizeWeatherCity(value?: string | null) {
  return (value || '').replace(/市/g, '').trim()
}

export function findWeatherDayForPlanDay(planDay: WeatherDisplayPlanDay, dailyWeather: WeatherDisplayDay[]) {
  const anchorCity = normalizeWeatherCity(planDay.anchor_city)
  const exact = dailyWeather.find(
    (item) => item.day === planDay.day && (!anchorCity || normalizeWeatherCity(item.city) === anchorCity),
  )
  if (exact) return exact
  if (anchorCity) {
    return dailyWeather.find((item) => item.day === planDay.day && !normalizeWeatherCity(item.city))
  }
  return dailyWeather.find((item) => item.day === planDay.day)
}

export function hasResolvedPlanWeather(planDay: WeatherDisplayPlanDay, weatherDay?: WeatherDisplayDay) {
  const summary = planDay.weather_summary || ''
  const badge = planDay.weather_badge || ''
  if (summary && !summary.includes('天气待确认')) return true
  if (badge && badge !== '天气待确认') return true
  if (!weatherDay) return false
  if (weatherDay.data_source === 'tencent_maps') return true
  if (weatherDay.data_source && weatherDay.data_source !== 'tencent_maps') return false
  const weather = weatherDay.weather || ''
  return Boolean(weather && !weather.includes('天气待确认') && !weather.includes('天气未知'))
}

export function isFallbackWeatherForDisplay(planDay: WeatherDisplayPlanDay, weatherDay?: WeatherDisplayDay, contextSource?: string) {
  if (hasResolvedPlanWeather(planDay, weatherDay)) return false
  if (!weatherDay) return true
  return (weatherDay?.data_source || contextSource) !== 'tencent_maps'
}

export function formatWeatherDisplayLine(planDay: WeatherDisplayPlanDay, weatherDay?: WeatherDisplayDay, isFallback = false) {
  if (isFallback) return `${planDay.anchor_city || weatherDay?.city || '目的地'} · 天气待确认`
  if (weatherDay?.weather && !weatherDay.weather.includes('天气待确认')) {
    return `${weatherDay.city || planDay.anchor_city || '目的地'} · ${weatherDay.weather} · ${weatherDay.temperature || '温度待确认'}`
  }
  return planDay.weather_summary || `${planDay.anchor_city || '目的地'} · 天气参考`
}

export function compactWeatherItems(items?: Array<string | null | undefined>, limit = 3) {
  const result: string[] = []
  for (const item of items || []) {
    const cleaned = (item || '').trim()
    if (cleaned && !result.includes(cleaned)) result.push(cleaned)
    if (result.length >= limit) break
  }
  return result
}
