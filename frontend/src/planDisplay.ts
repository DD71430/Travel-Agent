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
