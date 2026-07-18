export type PlanDayLike = {
  day: number
}

export function limitPlanDays<T extends PlanDayLike>(itinerary: T[] | undefined, durationDays?: number) {
  const days = Array.isArray(itinerary) ? itinerary : []
  if (!durationDays || durationDays < 1) return days
  return days.filter((item) => item.day >= 1 && item.day <= durationDays).slice(0, durationDays)
}

export function replacePlanResult<T>(_current: T | null, incoming: T) {
  return incoming
}

export type DayDetailsLike = {
  meals?: string[]
  hotel_hint?: string | null
}

export function getDayDetailsSummary(day: DayDetailsLike) {
  if (day.meals?.length || day.hotel_hint) return '查看餐饮、住宿与调度说明'
  return '查看完整调度说明'
}

export function formatBackupItemsBanner(items?: string[]) {
  const names = Array.from(new Set((items || []).map((item) => item.trim()).filter(Boolean)))
  if (!names.length) return ''
  return `备选/未排入主线：${names.join('、')}。建议根据天气、体力或延长停留取舍。`
}
