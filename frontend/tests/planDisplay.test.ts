import { limitPlanDays, replacePlanResult } from '../src/planDisplay.js'

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message)
}

const itinerary = [
  { day: 1, anchor_city: '徐州' },
  { day: 2, anchor_city: '徐州' },
  { day: 3, anchor_city: '济南' },
  { day: 4, anchor_city: '济南' },
  { day: 5, anchor_city: '济南' },
]

const visible = limitPlanDays(itinerary, 3)
assert(visible.length === 3, 'a three-day plan must not render Day 4 or Day 5')
assert(visible.map((item) => item.anchor_city).join(',') === '徐州,徐州,济南', 'visible days must preserve the planned city order')

const oldPlan = { id: 'old', daily_itinerary: itinerary }
const newPlan = { id: 'new', daily_itinerary: itinerary.slice(0, 3) }
const currentPlan = replacePlanResult(oldPlan, newPlan)
assert(currentPlan === newPlan, 'an incoming plan must replace the previous plan object')
