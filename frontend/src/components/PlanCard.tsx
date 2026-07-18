import { useState } from 'react'
import { formatBackupItemsBanner, getDayDetailsSummary, limitPlanDays } from '../planDisplay.js'
import type { RouteDebug, TravelPlanResponse, TripDayPlan, WeatherDay } from '../types.js'
import { compactWeatherItems, findWeatherDayForPlanDay, formatWeatherDisplayLine, isFallbackWeatherForDisplay } from '../weatherDisplay.js'

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function getDataSourceLabel(value?: string) {
  if (!value) return 'unknown'
  if (value === 'tencent_maps') return '腾讯地图真实返回'
  if (value === 'weather_service') return '实时天气参考'
  if (value === 'poi_search') return '周边 POI 真实返回'
  if (value === 'fallback') return '兜底规划'
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

function getWeatherConditionBadge(weather?: string) {
  const text = (weather || '').trim()
  if (!text || text.includes('待确认') || text.includes('未知')) return ''
  if (text.includes('暴') || text.includes('雷')) return '预警'
  if (text.includes('雨')) return '雨天'
  if (text.includes('雪')) return '雪天'
  if (text.includes('雾') || text.includes('霾')) return '雾霾'
  if (text.includes('阴')) return '阴天'
  if (text.includes('多云') || text.includes('少云')) return '多云'
  if (text.includes('晴')) return '晴天'
  return ''
}

function getWeatherBadge(day?: WeatherDay, isFallback = false) {
  if (!day) return '天气待确认'
  if (isFallback) return '天气待确认'
  const tagText = (day.weather_tags || []).join(',')
  if (tagText.includes('weather_risk')) return '预警'
  if (tagText.includes('rain')) return '雨天'
  if (tagText.includes('heat')) return '高温'
  const conditionBadge = getWeatherConditionBadge(day.weather)
  if (conditionBadge) return conditionBadge
  if (day.indoor_priority) return '室内优先'
  if (day.outdoor_suitability === 'good') return '室外适合'
  return '天气已查询'
}

function getDisplayWeatherBadge(planBadge: string | null | undefined, day?: WeatherDay, isFallback = false) {
  const inferredBadge = getWeatherBadge(day, isFallback)
  if (!planBadge) return inferredBadge
  if (['天气参考', '天气已查询', '室外适合', '室内优先'].includes(planBadge) && inferredBadge !== '天气待确认') {
    return inferredBadge
  }
  return planBadge
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
    mixed: '地铁 + 打车/网约车',
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

function formatRouteIssue(routeError?: string | null, locationDebug?: Record<string, unknown> | null) {
  const reason = typeof locationDebug?.reason === 'string' ? locationDebug.reason : ''
  const detail = (routeError || '').replace(/^Geocode failed:\s*/i, '').trim()
  if (!reason && !detail) return ''
  if (reason === 'geocode_failed') {
    return `地址解析失败${detail ? `：${detail}` : ''}。请检查途经点、景点或城市名是否被写成了完整动作短语。`
  }
  if (reason === 'unsupported_mode') {
    return `路线服务暂不支持当前交通方式${detail ? `：${detail}` : ''}。`
  }
  if (detail.includes('公共交通') || detail.includes('公交')) {
    return `公共交通路线不可用${detail ? `：${detail}` : ''}。`
  }
  if (reason && reason !== 'success') {
    return `路线服务失败${detail ? `：${detail}` : `：${reason}`}。`
  }
  return ''
}

type PlanCardProps = {
  plan: TravelPlanResponse
}

export function PlanCard({ plan }: PlanCardProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'daily' | 'weather' | 'debug'>('daily')
  const routeDebug = isObject(plan.raw_route) ? (plan.raw_route as RouteDebug) : null
  const locationDebug = isObject(routeDebug?.location_debug) ? routeDebug?.location_debug : null
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
  const backupWaypoints = Array.isArray(routeDebug?.backup_waypoints) ? routeDebug?.backup_waypoints : []
  const backupWaypointNames = backupWaypoints.map((item) => String(item?.name || '')).filter(Boolean)
  const reservationTips = dedupeStrings(Array.isArray(routeDebug?.reservation_tips) ? routeDebug?.reservation_tips : [])
  const routeHighlights = plan.route_highlights || []
  const weatherOverview = plan.weather_overview || weatherPlanSummary?.weather_overview || weatherContext?.summary || plan.weather_hint || '天气待确认'
  const weatherAdjustments = dedupeStrings(plan.weather_adjustments?.length ? plan.weather_adjustments : weatherPlanSummary?.weather_adjustments)
  const packingSummary = dedupeStrings(plan.packing_summary?.length ? plan.packing_summary : weatherPlanSummary?.packing_summary)
  const dailyWeatherBriefs = dedupeStrings(weatherPlanSummary?.daily_weather_briefs)
  const visibleDailyItinerary = limitPlanDays(plan.daily_itinerary, plan.duration_days)
  const scheduledAttractionNames = dedupeStrings(
    visibleDailyItinerary.flatMap((day) => (day.attractions || []).map((item) => item.name || '')),
  )
  const scenicTexts = dedupeStrings([...scheduledAttractionNames, ...(plan.attraction_recommendations || [])])
  const memoryLabel = getMemoryStatusLabel(plan.response_meta)
  const sourceLabel = getDataSourceLabel(plan.data_source)
  const intercityMode = getProfileString(tripProfile, 'intercity_mode') || String(routeDebug?.request_debug?.travel_mode || '')
  const localMode = getProfileString(tripProfile, 'local_mode')
  const intercityLabel = getProfileString(tripProfile, 'intercity_label') || getTransportModeLabel(intercityMode)
  const localLabel = getProfileString(tripProfile, 'local_label') || (localMode ? getTransportModeLabel(localMode, true) : '')
  const transportDisplay = localLabel && localLabel !== intercityLabel ? `${intercityLabel} + ${localLabel}` : intercityLabel || '--'
  const routeIssue = formatRouteIssue(plan.route_error, locationDebug)
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
    const weatherTips = compactWeatherItems(day.weather_tips?.length ? day.weather_tips : weatherDay?.weather_tips, 3)
    const packingTips = compactWeatherItems(day.packing_tips?.length ? day.packing_tips : weatherDay?.packing_tips, 3)
    const badge = getDisplayWeatherBadge(day.weather_badge, weatherDay, isFallbackWeather)
    const tone = getWeatherTone(badge, day.weather_tags?.length ? day.weather_tags : weatherDay?.weather_tags, isFallbackWeather)
    const displayNotes = getDisplayNotes(day)
    const keyNotes = displayNotes.slice(0, 2)
    const weatherNoteItems = compactWeatherItems([...(day.weather_adjustments || []), ...weatherTips], 3)
    const backupAttractions = day.backup_attractions || []
    const dayReservationTips = dedupeStrings(day.reservation_tips || [])
    return (
      <article key={day.day} className="day-card">
        <div className="day-card-head">
          <strong>Day {day.day}</strong>
          <span>{day.anchor_city || '当天城市'} · {day.route_segment || '按当日景点顺序串联'}</span>
          <em>{getStageLabel(day.stage)}</em>
          <em className={`weather-stage-badge ${tone}`}>{badge}</em>
        </div>
        <div className={`weather-chip-row ${tone}`}>
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
              {weatherNoteItems.map((tip) => <li key={tip}>{tip}</li>)}
            </ul>
          </div>
        ) : null}
        {!isFallbackWeather && packingTips.length ? (
          <div className="packing-chip-row">
            {packingTips.map((tip) => <span key={tip}>{tip}</span>)}
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
        {backupAttractions.length ? (
          <div className="note-row">
            {backupAttractions.map((item) => <span key={`${day.day}-backup-${item.name}`}>备选：{item.name}{item.reason ? ` · ${item.reason}` : ''}</span>)}
          </div>
        ) : null}
        {dayReservationTips.length ? (
          <div className="note-row">
            {dayReservationTips.map((tip) => <span key={`${day.day}-reservation-${tip}`}>预约提醒：{tip}</span>)}
          </div>
        ) : null}
        <details className="day-details">
          <summary>{getDayDetailsSummary(day)}</summary>
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
      {routeIssue ? (
        <div className="fallback-banner">{routeIssue}</div>
      ) : null}
      <div className={`weather-banner${weatherContext?.data_source === 'fallback' ? ' warning' : ' resolved'}`}>
        <strong>{weatherContext?.data_source === 'fallback' ? '天气待确认' : '天气已融入行程'}</strong>
        <span>{weatherContext?.data_source === 'fallback' ? '建议出行前查看实时天气；本行程保留室内/室外备选。' : weatherOverview}</span>
      </div>
      {unscheduledWaypoints.length ? (
        <div className="fallback-banner">未安排途经点/景点：{unscheduledWaypoints.join('、')}。建议延长停留或作为备选。</div>
      ) : null}
      {backupWaypointNames.length ? (
        <div className="fallback-banner">{formatBackupItemsBanner(backupWaypointNames)}</div>
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
          {reservationTips.length ? (
            <div className="plan-section">
              <h4>预约提醒</h4>
              <ul>{reservationTips.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}
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
