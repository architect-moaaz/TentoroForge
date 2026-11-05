// React Native's built-in fetch cannot stream. `expo/fetch` can, so the live
// streams (project events, the build chat) read through it.
import { fetch as streamFetch } from 'expo/fetch';

import { getAccessToken } from './api';
import { API_BASE } from './config';

export type SseFrame = { event: string; data: Record<string, unknown> };

/** Reads a server-sent-events response and calls `onFrame` for each frame.
 *  Resolves when the stream ends; throws on a failed request. */
export async function readSse(
  path: string,
  init: { method?: string; body?: unknown },
  onFrame: (frame: SseFrame) => void,
  signal: AbortSignal,
): Promise<void> {
  const token = getAccessToken();
  const res = await streamFetch(`${API_BASE}${path}`, {
    method: init.method ?? 'GET',
    headers: {
      Accept: 'text/event-stream',
      ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    signal,
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Stream failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let event = 'message';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const raw of lines) {
      const line = raw.replace(/\r$/, '');
      if (line.startsWith('event:')) {
        event = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(line.slice(5).trim());
        } catch {
          /* a frame that is not JSON carries nothing we use */
        }
        onFrame({ event, data });
      } else if (line === '') {
        event = 'message';
      }
    }
  }
}
