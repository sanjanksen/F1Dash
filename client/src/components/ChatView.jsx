import { useState, useRef, useEffect } from 'react'
import AnswerRenderer from './AnswerRenderer.jsx'

const SUGGESTIONS = [
  { label: 'Race Story', text: 'How did Russell do at Suzuka?' },
  { label: 'Team Weekend', text: 'How did Ferrari do this weekend?' },
  { label: 'Race Report', text: 'Give me the Japanese GP race recap' },
  { label: 'Qualifying', text: 'Why was Norris faster than Leclerc in qualifying?' },
]

export default function ChatView({ messages, loading, onSend }) {
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const year = new Date().getFullYear()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    if (!loading) inputRef.current?.focus()
  }, [loading])

  const handleSend = (text) => {
    const msg = text.trim()
    if (!msg || loading) return
    setInput('')
    onSend(msg)
  }

  const isIntro = messages.length === 0 && !loading

  return (
    <div className="chat-wrap">
      <div className="chat-scroll">
        {isIntro && (
          <div className="chat-intro animate-in">
            <div className="chat-intro-badge">F1</div>
            <span className="chat-intro-kicker">Race Intelligence</span>
            <h1 className="chat-intro-title">Ask for the story,<br />not just the stat.</h1>
            <p className="chat-intro-sub">
              Weekend recaps, race reports, team summaries, safety car impact,
              qualifying progression, or telemetry-led analysis for the {year} season.
            </p>
            <div className="suggestion-grid">
              {SUGGESTIONS.map(s => (
                <button
                  key={s.text}
                  className="suggestion-card"
                  onClick={() => handleSend(s.text)}
                >
                  <span className="suggestion-label">{s.label}</span>
                  <span className="suggestion-text">{s.text}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.length > 0 && (
          <div className="chat-messages">
            {messages.map((msg, i) => (
              <div
                key={msg.id}
                className={`message-row ${msg.role} animate-in`}
                style={{ animationDelay: `${Math.min(i * 0.02, 0.2)}s` }}
              >
                {msg.role === 'assistant' && (
                  <div className="msg-avatar">F1</div>
                )}
                <div className={`message-content ${msg.role}${msg.isError ? ' error' : ''}`}>
                  {msg.role === 'assistant' && !msg.isError
                    ? <AnswerRenderer text={msg.text} />
                    : msg.text}
                </div>
              </div>
            ))}

            {loading && (
              <div className="message-row assistant animate-in">
                <div className="msg-avatar">F1</div>
                <div className="message-content typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}

        {isIntro && <div ref={bottomRef} />}
      </div>

      <div className="chat-bottom">
        <div className="chat-bottom-inner">
          <form
            className="chat-input-row"
            onSubmit={e => { e.preventDefault(); handleSend(input) }}
          >
            <input
              ref={inputRef}
              className="chat-input"
              type="text"
              placeholder="Ask about a driver, team, race, safety car, or qualifying story..."
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading}
            />
            <button
              className="send-btn"
              type="submit"
              disabled={loading || !input.trim()}
              aria-label="Send"
            >
              {loading ? (
                <span className="send-spinner" />
              ) : (
                <svg viewBox="0 0 20 20" fill="none" width="16" height="16">
                  <path
                    d="M3 10h14M17 10l-6-6M17 10l-6 6"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
          </form>
          <p className="chat-hint">Structured F1 replies powered by FastF1, Jolpica, and route-aware tooling.</p>
        </div>
      </div>
    </div>
  )
}
