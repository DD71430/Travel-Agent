import type { QuickAction } from './chatUi.js'
import { formatHistoryTime } from './chatUi.js'

export type SidebarHistoryEntry = {
  id: string
  title: string
  summary: string
  updatedAt?: string
  active?: boolean
}

type SidebarPanelProps = {
  quickActions: QuickAction[]
  historyEntries: SidebarHistoryEntry[]
  memoryLabel: string
  memoryConnected: boolean
  onSelectPrompt: (action: QuickAction) => void
  onSelectHistory: (id: string) => void
  onNewConversation: () => void
  onClose?: () => void
}

export function SidebarPanel({
  quickActions,
  historyEntries,
  memoryLabel,
  memoryConnected,
  onSelectPrompt,
  onSelectHistory,
  onNewConversation,
  onClose,
}: SidebarPanelProps) {
  return (
    <div className="sidebar-panel">
      <div className="sidebar-toolbar">
        <div>
          <span className="sidebar-kicker">工作区</span>
          <strong>行程助手</strong>
        </div>
        <div className="sidebar-toolbar-actions">
          {onClose ? (
            <button type="button" className="icon-button sidebar-close" title="关闭历史侧栏" aria-label="关闭历史侧栏" onClick={onClose}>×</button>
          ) : null}
          <button type="button" className="icon-button" title="新建会话" aria-label="新建会话" onClick={onNewConversation}>＋</button>
        </div>
      </div>

      <section className="sidebar-section quick-section" aria-labelledby="quick-actions-title">
        <h2 id="quick-actions-title">快捷指令</h2>
        <div className="quick-action-list">
          {quickActions.map((action) => (
            <button key={action.id} type="button" onClick={() => onSelectPrompt(action)}>
              <span>{action.label}</span>
              <small>{action.prompt}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="sidebar-section history-section" aria-labelledby="history-title">
        <div className="sidebar-section-head">
          <h2 id="history-title">历史记录</h2>
          <span>{historyEntries.length}</span>
        </div>
        <div className="history-list">
          {historyEntries.length ? historyEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`history-item${entry.active ? ' active' : ''}`}
              onClick={() => onSelectHistory(entry.id)}
            >
              <span className="history-item-head">
                <strong>{entry.title}</strong>
                {entry.updatedAt ? <time>{formatHistoryTime(entry.updatedAt)}</time> : null}
              </span>
              <span className="history-summary">{entry.summary || '暂无摘要'}</span>
            </button>
          )) : <p className="empty-history">暂无历史记录</p>}
        </div>
      </section>

      <footer className="memory-status">
        <span className={`memory-dot${memoryConnected ? ' connected' : ''}`} aria-hidden="true" />
        <span>{memoryLabel}</span>
      </footer>
    </div>
  )
}
