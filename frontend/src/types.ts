export type Role = 'user' | 'assistant'

export type Message = {
  role: Role
  content: string
}

export type RouteStep = {
  instruction: string
  distance?: string | null
  duration?: string | null
  road_name?: string | null
  direction?: string | null
  action?: string | null
}

export type RouteOption = {
  title: string
  summary: string
  distance: string
  duration: string
  reasons: string[]
  steps: RouteStep[]
  mode?: string | null
  tags?: string[]
  toll?: number | string | null
  traffic_light_count?: number | null
  waypoint_summary?: string | null
}

export type ScenicHighlight = {
  title: string
  detail?: string
}

export type TransportBlock = {
  mode?: string
  label?: string
  origin?: string
  destination?: string
  ride_minutes?: number | string
  buffer_minutes?: number | string
  total_minutes?: number | string
  summary?: string
}

export type RouteDebug = {
  generated_at?: string
  origin_point?: string | null
  destination_point?: string | null
  best_option?: RouteOption
  weather_hint?: string
  attractions?: string[]
  hotel_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  food_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  request_debug?: Record<string, unknown>
  location_debug?: Record<string, unknown>
  trip_profile?: Record<string, unknown>
  weather_context?: WeatherContext
  weather_plan_summary?: WeatherPlanSummary
  waypoint_details?: WaypointDetail[]
  must_visit_attractions?: string[]
  waypoint_order_mode?: string
  unscheduled_waypoints?: string[]
  backup_waypoints?: { name?: string; reason?: string; tags?: string }[]
  reservation_tips?: string[]
  stage_segments?: { transport_block?: TransportBlock }[]
}

export type WeatherDay = {
  day?: number
  city?: string
  weather?: string
  temperature?: string
  outdoor_suitability?: string
  indoor_priority?: boolean
  strategy?: string
  weather_tips?: string[]
  packing_tips?: string[]
  weather_tags?: string[]
  data_source?: string
  fallback_reason?: string | null
  adcode?: string | null
}

export type WeatherContext = {
  data_source?: string
  summary?: string
  daily_weather?: WeatherDay[]
  request_debug?: Record<string, unknown>
}

export type WeatherPlanSummary = {
  weather_overview?: string
  daily_weather_briefs?: string[]
  weather_adjustments?: string[]
  packing_summary?: string[]
}

export type WeatherQueryData = {
  city?: string
  adcode?: string | null
  connected?: boolean
  data_source?: string
  fallback_reason?: string | null
  summary?: string
  daily_weather?: WeatherDay[]
  weather_tips?: string[]
  packing_tips?: string[]
  debug?: Record<string, unknown>
  response_meta?: Record<string, unknown>
}

export type ConversationTurn = {
  user_input: string
  assistant_output: string
}

export type ConversationSummary = {
  conversation_id: string
  title?: string
  last_user_input?: string
  last_assistant_output?: string
  updated_at?: string
  intent?: string
}

export type MemoryStatus = {
  backend?: string
  connected?: boolean
  fallback_reason?: string
  [key: string]: unknown
}

export type ConversationListResponse = {
  conversations?: ConversationSummary[]
  meta?: { memory?: MemoryStatus }
}

export type ConversationHistoryResponse = {
  conversation_id?: string
  history?: ConversationTurn[]
  meta?: { memory?: MemoryStatus }
}

export type WaypointDetail = {
  name: string
  type?: string
  must_visit?: boolean
  source?: string
  order?: number
}

export type TripDayPlan = {
  day: number
  title: string
  stage?: 'route' | 'destination' | 'buffer' | string
  anchor_city?: string | null
  route_segment?: string
  segment_data_source?: string | null
  drive_time?: string
  visit_time?: string
  weather_strategy?: string | null
  weather_summary?: string
  weather_adjustments?: string[]
  weather_badge?: string | null
  weather_tips?: string[]
  packing_tips?: string[]
  weather_tags?: string[]
  transport_block?: TransportBlock | null
  morning: string
  afternoon: string
  evening: string
  attractions?: { name: string; address?: string; category?: string; reason?: string; tags?: string; must_visit?: string }[]
  backup_attractions?: { name: string; address?: string; category?: string; reason?: string; tags?: string; must_visit?: string }[]
  reservation_tips?: string[]
  meals?: string[]
  hotel_hint?: string | null
  recommendation_reasons?: string[]
  tags?: string[]
  notes?: string[]
}

export type TravelPlanResponse = {
  conversation_id: string
  intent: string
  scenario: string
  summary: string
  route_title: string
  trip_type?: string
  route_total_duration?: string
  route_total_distance?: string
  trip_overview?: string
  duration_days?: number
  budget_estimate?: string
  accommodation_suggestion?: string
  transportation_suggestion?: string[]
  weather_hint?: string
  weather_overview?: string
  weather_adjustments?: string[]
  packing_summary?: string[]
  attraction_recommendations?: string[]
  hotel_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  food_candidates?: { name: string; address?: string; category?: string; location?: string }[]
  scenic_route_highlights?: string[]
  route_highlights?: ScenicHighlight[]
  daily_itinerary?: TripDayPlan[]
  travel_tips?: string[]
  route_steps?: RouteStep[]
  route_options?: RouteOption[]
  recommendation_reasons?: string[]
  user_preferences?: string[]
  history?: ConversationTurn[]
  raw_route?: Record<string, unknown>
  response_meta?: Record<string, unknown>
  data_source?: string
  confidence?: string
  route_error?: string | null
}

export type UploadContext = {
  filename: string
  content_type: string
  size: number
  file_kind?: string
  extracted_text?: string
  extraction_error?: string
  audio_debug?: Record<string, unknown>
}

export type AudioDebugPanel = {
  input_suffix?: string
  content_type?: string
  input_size?: number
  converted_size?: number
  status_code?: number
  response_keys?: string[]
  result_type?: string
  transcript_preview?: string
  choices_count?: number
  choice_keys?: string[]
  stage?: string
  error_type?: string
  error_message?: string
}

export type TravelRequestDebug = {
  origin?: string
  destination?: string
  travel_mode?: string
  preferences?: string | null
  source_query?: string | null
  trip_profile?: Record<string, unknown>
  waypoint_order?: boolean
  waypoints?: { name: string }[]
}

export type NearbyCandidate = {
  name: string
  address?: string
  category?: string
  location?: string
  id?: string
}

export type NearbyDebug = {
  city?: string
  anchor?: string
  anchor_point?: string | null
  anchor_debug?: Record<string, unknown> | null
  destination_point?: string | null
  attraction_recommendations?: string[]
  transportation_suggestion?: string[]
  hotel_candidates?: NearbyCandidate[]
  food_candidates?: NearbyCandidate[]
  debug?: Record<string, unknown> | null
}

export type UnifiedChatResponse = {
  conversation_id: string
  answer_type: 'travel_planning' | 'nearby_search' | 'general_chat' | 'weather_query'
  final_answer: string
  data?: {
    travel_plan?: TravelPlanResponse | null
    nearby?: NearbyDebug | null
    weather?: WeatherQueryData | null
  }
  travel_request?: TravelRequestDebug | null
  upload_context?: UploadContext | null
  meta?: Record<string, unknown>
  error?: string | null
}
