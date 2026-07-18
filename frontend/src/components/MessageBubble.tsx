import type { Message } from '../types.js'

type MessageBubbleProps = {
  message: Message
}

export function MessageBubble({ message }: MessageBubbleProps) {
  return (
    <article className={`message ${message.role}`}>
      <span className="message-role">{message.role === 'user' ? '我' : 'Agent'}</span>
      <p>{message.content}</p>
    </article>
  )
}
