/**
 * Server-sent events over fetch (design D5): POST a body, read `event:`/`data:` frames from the
 * response stream, abort with an AbortController. EventSource cannot POST, hence fetch.
 */
import { ApiError, errorFrom, url } from './client'

export interface SseHandlers<TDone> {
  onDelta: (text: string) => void
  onDone: (done: TDone) => void
  onError: (error: ApiError) => void
}

export interface SseStream {
  abort: () => void
  finished: Promise<'done' | 'error' | 'aborted'>
}

/** Parse complete frames out of a buffer; returns the unconsumed remainder. */
export function parseFrames(buffer: string, emit: (event: string, data: string) => void): string {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const frames = normalized.split('\n\n')
  const rest = frames.pop() ?? ''
  for (const frame of frames) {
    let event = 'message'
    const data: string[] = []
    for (const line of frame.split('\n')) {
      if (line.startsWith(':')) continue // comment / keep-alive ping
      const idx = line.indexOf(':')
      const field = idx === -1 ? line : line.slice(0, idx)
      const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '')
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length) emit(event, data.join('\n'))
  }
  return rest
}

export function postSse<TDone>(path: string, body: unknown, handlers: SseHandlers<TDone>): SseStream {
  const controller = new AbortController()
  const finished = (async (): Promise<'done' | 'error' | 'aborted'> => {
    let outcome: 'done' | 'error' | null = null
    try {
      const res = await fetch(url(path), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!res.ok || !res.body) {
        handlers.onError(await errorFrom(res))
        return 'error'
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      const emit = (event: string, data: string) => {
        const payload = JSON.parse(data)
        if (event === 'delta') handlers.onDelta(payload.text as string)
        else if (event === 'done') {
          outcome = 'done'
          handlers.onDone(payload as TDone)
        } else if (event === 'error') {
          outcome = 'error'
          handlers.onError(new ApiError(payload.code, payload.message, 200))
        }
      }
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer = parseFrames(buffer + decoder.decode(value, { stream: true }), emit)
      }
      parseFrames(buffer + decoder.decode() + '\n\n', emit)
      if (!outcome) {
        handlers.onError(new ApiError('stream_ended', 'הזרם הסתיים לפני שהתקבלה תשובה מלאה', 200))
        return 'error'
      }
      return outcome
    } catch (e) {
      if ((e as Error).name === 'AbortError') return 'aborted'
      handlers.onError(new ApiError('network_error', 'החיבור לשרת נכשל', 0))
      return 'error'
    }
  })()
  return { abort: () => controller.abort(), finished }
}
