// client/src/components/ChatView.jsx
import { useState, useRef, useEffect } from 'react'
import { sendChatMessage } from '../api/f1api.js'

const SUGGESTIONS = [
  "Who leads the 2025 championship?",
  "How has Verstappen performed this season?",
  "Which races are coming up next?",
  "Compare Norris and Leclerc this season",
]

export default function ChatView() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Ask me anything about the 2025 Formula 1 season — driver performance, standings, race results, or circuit comparisons.",
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text) => {
    const msg = text.trim()
    if (!msg || loading) return

    setMessages(prev => [...prev, { role: 'user', text: msg }])
    setInput('')
    setLoading(true)

    try {
      const { response } = await sendChatMessage(msg)
      setMessages(prev => [...prev, { role: 'assistant', text: response }])
    } catch (e) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: `Something went wrong: ${e.message}`, isError: true },
      ])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 60)
    }
  }

  const isIntro = messages.length === 1

  return (
    <div className="chat-container">
      {/* Suggestion chips — visible only before the first user message */}
      {isIntro && (
        <div className="chat-intro animate-in">
          <div className="chat-avatar-lg">
            F<span>1</span>
          </div>
          <p className="chat-intro-label">Your F1 Analyst</p>
          <div className="suggestion-chips">
            {SUGGESTIONS.map(s => (
              <button key={s} className="suggestion-chip" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Message list */}
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`bubble-row ${msg.role} animate-in`}
            style={{ animationDelay: `${i * 0.025}s` }}
          >
            {msg.role === 'assistant' && (
              <div className="chat-avatar">F<span>1</span></div>
            )}
            <div className={`chat-bubble ${msg.role}${msg.isError ? ' error' : ''}`}>
              {msg.text}
            </div>
          </div>
        ))}

        {loading && (
          <div className="bubble-row assistant animate-in">
            <div className="chat-avatar">F<span>1</span></div>
            <div className="chat-bubble assistant typing">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input row */}
      <form
        className="chat-input-row"
        onSubmit={e => { e.preventDefault(); send(input) }}
      >
        <input
          ref={inputRef}
          className="chat-input"
          type="text"
          placeholder="Ask about any driver, race, or circuit…"
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <button
          className="send-btn"
          type="submit"
          disabled={loading || !input.trim()}
          aria-label="Send"
        >
          <svg viewBox="0 0 20 20" fill="none" width="17" height="17">
            <path d="M3 10h14M17 10l-6-6M17 10l-6 6"
              stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </div>
  )
}
