import { useEffect, useRef, useState } from 'react'
import { ArrowUp, ChevronRight } from 'lucide-react'

import AnswerRenderer from './AnswerRenderer.jsx'
import { Button } from './ui/button.jsx'
import { Input } from './ui/input.jsx'
import { fetchCircuits } from '../api/f1api.js'

export default function ChatView({ messages, loading, onSend }) {
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const year = new Date().getFullYear()
  const [lastRound, setLastRound] = useState(null)
  const [loadingTooLong, setLoadingTooLong] = useState(false)

  useEffect(() => {
    fetchCircuits()
      .then((circuits) => {
        const today = new Date().toISOString().slice(0, 10)
        const completed = circuits.filter((c) => c.date < today)
        if (completed.length > 0) {
          setLastRound(completed[completed.length - 1])
        }
      })
      .catch(() => {
        // Silently fall back to static suggestions
      })
  }, [])

  const shortName = lastRound
    ? lastRound.event_name.replace(' Grand Prix', ' GP')
    : 'the latest race'

  const suggestions = [
    { label: 'Race story', text: `How did Russell do at ${shortName}?` },
    { label: 'Team weekend', text: `How did Ferrari do at ${shortName}?` },
    { label: 'Race report', text: `Give me the ${shortName} race recap` },
    { label: 'Qualifying', text: `Why was Norris faster than Leclerc in qualifying at ${shortName}?` },
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
      <div className="app-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto">
        {isIntro ? (
          <div className="mx-auto flex min-h-full w-full max-w-4xl flex-1 flex-col justify-center px-6 py-10 lg:px-10">
            <div className="max-w-2xl">
              <div className="mb-4 text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
                F1 race intelligence
              </div>
              <h1 className="max-w-xl text-[2.55rem] font-semibold tracking-[-0.045em] text-foreground sm:text-[3.35rem]">
                Ask for the weekend, not just the number.
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-[15px]">
                Structured race stories, driver recaps, team summaries, qualifying progression,
                safety car impact, and telemetry-led answers for the {year} season.
              </p>
            </div>

            <div className="mt-9 grid gap-2.5 md:grid-cols-2">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion.text}
                  type="button"
                  onClick={() => handleSend(suggestion.text)}
                  className="group flex items-start justify-between rounded-md border border-border/90 bg-card px-4 py-3.5 text-left transition-colors hover:bg-secondary"
                >
                  <div>
                    <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                      {suggestion.label}
                    </div>
                    <div className="mt-1.5 text-sm leading-6 text-foreground">
                      {suggestion.text}
                    </div>
                  </div>
                  <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-7 px-6 py-7 lg:px-10">
            {messages.map((message) => (
              <div key={message.id} className="flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    {message.role === 'assistant' ? 'F1 Dash' : 'You'}
                  </div>
                  <div className="h-px flex-1 bg-border/80" />
                </div>

                {message.role === 'assistant' && !message.isError ? (
                  <AnswerRenderer text={message.text} widgets={message.widgets || []} />
                ) : (
                  <div
                    className={
                      message.isError
                        ? 'max-w-3xl rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm leading-7 text-destructive-foreground'
                        : 'max-w-3xl rounded-md border border-border/90 bg-card px-4 py-3 text-sm leading-7 text-foreground'
                    }
                  >
                    {message.text}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    F1 Dash
                  </div>
                  <div className="h-px flex-1 bg-border/80" />
                </div>
                <div className="inline-flex w-fit items-center gap-2 rounded-md border border-border/90 bg-card px-4 py-3 text-sm text-muted-foreground">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60" />
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60 [animation-delay:120ms]" />
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60 [animation-delay:240ms]" />
                </div>
                {loadingTooLong && (
                  <div className="text-xs text-muted-foreground">
                    Fetching telemetry and session data — this may take a moment.
                  </div>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-border/90 bg-background">
        <div className="mx-auto w-full max-w-4xl px-6 py-3 lg:px-10">
          <form
            onSubmit={(event) => {
              event.preventDefault()
              handleSend(input)
            }}
            className="rounded-md border border-border/90 bg-card p-1.5"
          >
            <div className="flex items-center gap-2">
              <Input
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                disabled={loading}
                placeholder="Ask about a driver, team, race, safety car, or qualifying story..."
                className="h-9 border-0 bg-transparent px-2 shadow-none focus-visible:ring-0"
              />
              <Button type="submit" size="icon" disabled={loading || !input.trim()} className="h-9 w-9">
                <ArrowUp className="h-4 w-4" />
              </Button>
            </div>
          </form>
          <p className="mt-2 text-[11px] text-muted-foreground">
            FastF1, Jolpica, and route-aware tooling for structured F1 answers.
          </p>
        </div>
      </div>
    </div>
  )
}
