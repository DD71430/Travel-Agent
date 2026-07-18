import type { WeatherQueryData } from '../types.js'

function dedupeStrings(items?: string[]) {
  const result: string[] = []
  for (const item of items || []) {
    const cleaned = item.trim()
    if (cleaned && !result.includes(cleaned)) result.push(cleaned)
  }
  return result
}

function getWeatherTone(badge?: string | null, tags?: string[], isFallback = false) {
  const tagText = (tags || []).join(',')
  if (isFallback || badge === '天气待确认' || tagText.includes('weather_unconfirmed')) return 'fallback'
  if (badge === '雨天' || badge === '预警' || tagText.includes('rain')) return 'rain'
  if (badge === '高温' || badge === '晴热' || tagText.includes('heat') || tagText.includes('sun_exposure')) return 'heat'
  return 'normal'
}

type WeatherCardProps = {
  weather: WeatherQueryData
}

export function WeatherCard({ weather }: WeatherCardProps) {
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
