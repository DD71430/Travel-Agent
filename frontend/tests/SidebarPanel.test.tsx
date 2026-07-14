import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SidebarPanel } from '../src/SidebarPanel.js'
import { QUICK_ACTIONS } from '../src/chatUi.js'

function assert(condition: unknown, message: string) {
  if (!condition) throw new Error(message)
}

const markup = renderToStaticMarkup(createElement(SidebarPanel, {
  quickActions: QUICK_ACTIONS,
  historyEntries: [{
    id: 'conversation-1',
    title: '济南 → 杭州',
    summary: '三天两晚高铁旅行方案',
    updatedAt: '2026-07-14T10:00:00+08:00',
    active: true,
  }],
  memoryLabel: 'Redis 已连接',
  memoryConnected: true,
  onSelectPrompt: () => undefined,
  onSelectHistory: () => undefined,
  onNewConversation: () => undefined,
}))

assert(!markup.includes('行程偏好'), 'the sidebar must not render the legacy trip preference heading')
assert(!markup.includes('生成路线方案'), 'the sidebar must not render the legacy plan submit button')
assert(markup.includes('旅行规划'), 'the sidebar should render the travel quick action')
assert(markup.includes('周边推荐'), 'the sidebar should render the nearby quick action')
assert(markup.includes('天气查询'), 'the sidebar should render the weather quick action')
assert(markup.includes('济南 → 杭州'), 'the sidebar should render conversation history')
assert(markup.includes('Redis 已连接'), 'the sidebar should render the memory status at the bottom')
