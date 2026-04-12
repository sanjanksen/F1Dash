import { useEffect, useRef, useState } from 'react'
import { ArrowUp, ChevronRight } from 'lucide-react'

import AnswerRenderer from './AnswerRenderer.jsx'
import { Button } from './ui/button.jsx'
import { Input } from './ui/input.jsx'

const suggestions = [
  { label: 'Race story', text: 'How did Russell do at Suzuka?' },
  { label: 'Team weekend', text: 'How did Ferrari do this weekend?' },
  { label: 'Race report', text: 'Give me the Japanese GP race recap' },
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
          <div className="mx-auto flex min-h-full w-full max-w-4xl flex-1 flex-col justify-center px-6 py-12 lg:px-10">
            <div className="max-w-2xl">
              <div className="mb-4 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                F1 race intelligence
              </div>
              <h1 className="max-w-xl text-4xl font-semibold tracking-[-0.04em] text-foreground sm:text-5xl">
                Ask for the weekend, not just the number.
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-muted-foreground sm:text-[15px]">
                Structured race stories, driver recaps, team summaries, qualifying progression,
                safety car impact, and telemetry-led answers for the {year} season.
              </p>
            </div>

            <div className="mt-10 grid gap-3 md:grid-cols-2">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion.text}
                  type="button"
                  onClick={() => handleSend(suggestion.text)}
                  className="group flex items-start justify-between rounded-lg border border-border bg-card px-4 py-4 text-left transition-colors hover:bg-secondary"
                >
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      {suggestion.label}
                    </div>
                    <div className="mt-2 text-sm leading-6 text-foreground">
                      {suggestion.text}
                    </div>
                  </div>
                  <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-8 lg:px-10">
            {messages.map((message) => (
              <div key={message.id} className="flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    {message.role === 'assistant' ? 'F1 Dash' : 'You'}
                  </div>
                  <div className="h-px flex-1 bg-border" />
                </div>

                {message.role === 'assistant' && !message.isError ? (
                  <AnswerRenderer text={message.text} />
                ) : (
                  <div
                    className={
                      message.isError
                        ? 'max-w-3xl rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm leading-7 text-destructive-foreground'
                        : 'max-w-3xl rounded-lg border border-border bg-card px-4 py-3 text-sm leading-7 text-foreground'
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
                  <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    F1 Dash
                  </div>
                  <div className="h-px flex-1 bg-border" />
                </div>
                <div className="inline-flex w-fit items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:120ms]" />
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:240ms]" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-border bg-background">
        <div className="mx-auto w-full max-w-4xl px-6 py-4 lg:px-10">
          <form
            onSubmit={(event) => {
              event.preventDefault()
              handleSend(input)
            }}
            className="rounded-lg border border-border bg-card p-2"
          >
            <div className="flex items-center gap-2">
              <Input
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                disabled={loading}
                placeholder="Ask about a driver, team, race, safety car, or qualifying story..."
                className="h-10 border-0 bg-transparent px-2 shadow-none focus-visible:ring-0"
              />
              <Button type="submit" size="icon" disabled={loading || !input.trim()} className="h-10 w-10">
                <ArrowUp className="h-4 w-4" />
              </Button>
            </div>
          </form>
          <p className="mt-2 text-xs text-muted-foreground">
            FastF1, Jolpica, and route-aware tooling for structured F1 answers.
          </p>
        </div>
      </div>
    </div>
  )
}
