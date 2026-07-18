import { PlanCard } from './PlanCard.js'
import { WeatherCard } from './WeatherCard.js'
import type { TravelPlanResponse, WeatherQueryData } from '../types.js'

type AnswerResultProps = {
  plan: TravelPlanResponse | null
  weather: WeatherQueryData | null
}

export function AnswerResult({ plan, weather }: AnswerResultProps) {
  if (!plan && !weather) return null

  return (
    <section className="answer-result" aria-label="结构化旅行结果">
      <div className="answer-result-head">
        <span>旅行 Agent 结果</span>
        <strong>{weather ? '天气与出行建议' : '路线与每日行程'}</strong>
      </div>
      {weather ? <WeatherCard weather={weather} /> : plan ? <PlanCard plan={plan} /> : null}
    </section>
  )
}
