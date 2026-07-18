import type { ChangeEvent } from 'react'

type ChatComposerProps = {
  input: string
  loading: boolean
  canSend: boolean
  uploadName: string
  uploadKind: 'image' | 'audio' | 'other' | ''
  uploadPreview: string
  uploadError: string
  error: string
  lastAudioDebugText: string
  showAudioDebug?: boolean
  onInputChange: (value: string) => void
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void | Promise<void>
  onClear: () => void
  onSend: () => void
}

export function ChatComposer({
  input,
  loading,
  canSend,
  uploadName,
  uploadKind,
  uploadPreview,
  uploadError,
  error,
  lastAudioDebugText,
  showAudioDebug = false,
  onInputChange,
  onFileChange,
  onClear,
  onSend,
}: ChatComposerProps) {
  return (
    <div className="composer">
      <textarea
        rows={3}
        value={input}
        onChange={(event) => onInputChange(event.target.value)}
        placeholder="例如：从济南到杭州三天两晚，乘高铁，途经徐州一天，偏好博物馆和经典景点…"
      />

      <div className="composer-actions">
        <div className="composer-toolbar">
          <div className="composer-tools">
            <label className="icon-button file-input" title="上传图片、文档、PDF 或语音" aria-label="上传图片、文档、PDF 或语音">
              <input
                type="file"
                accept="image/*,.pdf,.docx,.txt,.md,.csv,.log,.json,audio/*"
                onChange={(event) => {
                  void onFileChange(event)
                }}
              />
              <span aria-hidden="true">↑</span>
            </label>
            <span className="upload-name">{uploadName}</span>
          </div>
          <div className="composer-commands">
            <button type="button" className="icon-button" title="清空输入" aria-label="清空输入" onClick={onClear} disabled={loading}>×</button>
            <button type="button" className="primary-button send-button" onClick={onSend} disabled={!canSend}>
              {loading ? '发送中…' : '发送'}
            </button>
          </div>
        </div>

        {showAudioDebug && uploadKind === 'audio' && (uploadPreview || lastAudioDebugText) ? (
          <div className="debug-box">
            <strong>语音调试信息</strong>
            <pre>{uploadPreview || lastAudioDebugText}</pre>
          </div>
        ) : null}
        {uploadKind === 'image' && uploadPreview ? <p className="muted">图片状态：{uploadPreview}</p> : null}
        {uploadKind !== 'audio' && uploadKind !== 'image' && uploadPreview ? <p className="muted">识别内容预览：{uploadPreview}</p> : null}
        {uploadError ? <p className="error-text">{uploadError}</p> : null}
      </div>

      {error ? <p className="error-text">{error}</p> : null}
    </div>
  )
}
