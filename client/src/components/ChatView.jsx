import { useEffect, useRef, useState } from 'react'
import { ArrowUp, CornerDownRight } from 'lucide-react'

import AnswerRenderer from './AnswerRenderer.jsx'
import { Button } from './ui/button.jsx'
import { Input } from './ui/input.jsx'
import { fetchCircuits } from '../api/f1api.js'

export default function ChatView({ messages, loading, onSend }) {
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const [lastRound, setLastRound] = useState(null)
  const [loadingTooLong, setLoadingTooLong] = useState(false)

  useEffect(() => {
    fetchCircuits()
      .then((circuits) => {
        const today = new Date().toISOString().slice(0, 10)
        const completed = circuits.filter((c) => c.date < today)
        if (completed.length > 0) setLastRound(completed[completed.length - 1])
      })
      .catch(() => {})
  }, [])

  const shortName = lastRound ? lastRound.event_name.replace(' Grand Prix', ' GP') : 'the latest race'
  const suggestions = [
    `How did Russell do at ${shortName}?`,
    `Why was Norris faster than Leclerc in qualifying at ${shortName}?`,
    `Give me the ${shortName} race recap`,
    `How did Ferrari do at ${shortName}?`,
  ]

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    if (!loading) inputRef.current?.focus()
  }, [loading])

  useEffect(() => {
    if (!loading) {
      setLoadingTooLong(false)
      return
    }
    const timer = setTimeout(() => setLoadingTooLong(true), 15000)
    return () => clearTimeout(timer)
  }, [loading])

  const handleSend = (text) => {
    const next = text.trim()
    if (!next || loading) return
    setInput('')
    onSend(next)
  }

  const isIntro = messages.length === 0 && !loading

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto">
        {isIntro ? (
          <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-5 py-10 sm:px-8">
            <h1 className="max-w-2xl text-[2.15rem] font-semibold leading-[1.08] tracking-[-0.045em] text-foreground sm:text-[3.35rem]">
              What should we analyze?
            </h1>
            <p className="mt-4 max-w-xl text-[14px] leading-7 text-muted-foreground">
              Ask about race pace, qualifying deltas, strategy, driver form, or the next event.
            </p>

            <div className="mt-10 divide-y divide-border/70 border-y border-border/70">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => handleSend(suggestion)}
                  className="group flex w-full items-center gap-3 py-3.5 text-left text-[14px] leading-6 text-foreground transition-colors hover:text-primary"
                >
                  <CornerDownRight className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
                  <span>{suggestion}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-5 py-8 sm:px-8">
            {messages.map((message) => (
              <div
                key={message.id}
                className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
              >
                {message.role === 'assistant' && !message.isError ? (
                  <div className="w-full">
                    <div className="mb-2 text-[13px] text-muted-foreground">F1Dash</div>
                    <AnswerRenderer text={message.text} widgets={message.widgets || []} />
                  </div>
                ) : message.isError ? (
                  <div className="w-full rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm leading-7 text-foreground">
                    {message.text}
                  </div>
                ) : (
                  <div className="max-w-[78%] rounded-2xl bg-secondary px-4 py-3 text-sm leading-7 text-foreground">
                    {message.text}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div>
                <div className="mb-2 text-[13px] text-muted-foreground">F1Dash</div>
                <div className="inline-flex items-center gap-1.5 rounded-xl bg-card px-3 py-2">
                  <span className="h-1.5 w-1.5 rounded-sm bg-primary" style={{ animation: 'race-dot 1.1s 0ms ease-in-out infinite' }} />
                  <span className="h-1.5 w-1.5 rounded-sm bg-muted-foreground" style={{ animation: 'race-dot 1.1s 160ms ease-in-out infinite' }} />
                  <span className="h-1.5 w-1.5 rounded-sm bg-muted-foreground" style={{ animation: 'race-dot 1.1s 320ms ease-in-out infinite' }} />
                </div>
                {loadingTooLong && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    Fetching telemetry and session data. This can take a moment.
                  </div>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="bg-background px-4 pb-4 pt-2 sm:px-6">
        <div className="mx-auto w-full max-w-3xl">
          <form
            onSubmit={(event) => {
              event.preventDefault()
              handleSend(input)
            }}
            className="composer-shell rounded-2xl border border-border/80 bg-card/95 px-2 py-2 transition-colors focus-within:border-primary/45"
          >
            <div className="flex items-center gap-2">
              <Input
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                disabled={loading}
                placeholder="Ask F1Dash..."
                className="h-11 border-0 bg-transparent px-3 text-[15px] shadow-none focus-visible:ring-0"
              />
              <Button
                type="submit"
                size="icon"
                disabled={loading || !input.trim()}
                className="h-10 w-10 rounded-xl"
                aria-label="Send message"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
