import { Feather } from '@expo/vector-icons';
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Keyboard,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Markdown } from '@/components/markdown';
import { Avatar, Button } from '@/components/ui';
import { ApiError, apiJson, postJson } from '@/lib/api';
import { readSse, type SseFrame } from '@/lib/sse';
import { icon, radius, shadow, space, type, useColors, type Palette } from '@/theme';

interface Msg {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  at: string;
  /** What Smith offered to do next, as buttons (the web panel's chips). */
  options?: string[];
}

/** The review a build waits on: the requirements, then the product model (`/gates`). */
type Gate = 'requirements' | 'product_model' | null;

interface HistoryRow {
  id: string;
  role: Msg['role'];
  content: string;
  created_at?: string;
}


/** The request died on the way, not because the server refused it. */
function isConnectionDrop(e: unknown) {
  return e instanceof Error && /network|fetch failed|connection|timed out|aborted/i.test(e.message);
}

/** Machine messages like `[APPROVE_PLAN]` are not shown as chat bubbles. */
function isControlSignal(message: string) {
  return /^\[[A-Z_]+(:[^\]]*)?\](\s*\{[\s\S]*\})?$/.test(message.trim());
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const clock = (ms: number) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

/** The line under the chat while Smith works. A job we saw before the person sent their
 *  message is an earlier one, and theirs waits behind it (one job at a time per project). */
function workingLine(
  work: { text: string; since: number } | null,
  busy: boolean,
  sentAt: number,
  liveStatus: string | null,
): string {
  if (!work) return liveStatus ?? 'Smith is working…';
  if (busy && work.since < sentAt) {
    return `Smith is finishing an earlier job first, then your message is next.\nNow: ${work.text}`;
  }
  // The time is only honest for a job that began after the person sent their message; one we
  // joined part way through has been running longer than we have watched.
  return sentAt > 0 && work.since >= sentAt ? `${work.text} · ${clock(Date.now() - work.since)}` : work.text;
}

export function ChatView({ projectId, onApplied }: { projectId: string; onApplied: () => void }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [text, setText] = useState('');
  // The job Smith is running now (from the job feed), when we first saw it, and when we last sent.
  const [work, setWork] = useState<{ text: string; since: number } | null>(null);
  const [, setTick] = useState(0);
  const [sentAt, setSentAt] = useState(0);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  // Which door a message goes through: a project with a Living Blueprint takes
  // changes at /smith/turn; one without is still being discovered, planned and
  // built through the streaming /chat.
  const [hasBlueprint, setHasBlueprint] = useState(false);
  const turnAbort = useRef<AbortController | null>(null);
  const insets = useSafeAreaInsets();

  // The keyboard covers the screen without resizing it (iPhone, and Android edge to edge).
  // We find where this view ends on the screen and where the keyboard starts; the
  // difference is how far to lift the input.
  const root = useRef<ComponentRef<typeof View>>(null);
  const rootBottom = useRef(0);
  const kbTop = useRef<number | null>(null);
  const [kbOverlap, setKbOverlap] = useState(0);
  const recalc = useCallback(() => {
    const top = kbTop.current;
    setKbOverlap(top == null ? 0 : Math.max(0, Math.round(rootBottom.current - top)));
  }, []);
  const measureRoot = useCallback(() => {
    root.current?.measureInWindow((_x, y, _w, h) => {
      rootBottom.current = y + h;
      recalc();
    });
  }, [recalc]);
  useEffect(() => {
    const show = Keyboard.addListener(Platform.OS === 'ios' ? 'keyboardWillChangeFrame' : 'keyboardDidShow', (e) => {
      kbTop.current = e.endCoordinates.screenY;
      measureRoot();
    });
    const hide = Keyboard.addListener(Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide', () => {
      kbTop.current = null;
      recalc();
    });
    return () => {
      show.remove();
      hide.remove();
    };
  }, [measureRoot, recalc]);

  const addMsg = useCallback((role: Msg['role'], content: string, id?: string, options?: string[]) => {
    if (!content) return;
    const msgId = id ?? `${Date.now()}-${Math.random()}`;
    const opts = options?.length ? { options } : {};
    setMessages((prev) =>
      prev.some((m) => m.id === msgId)
        ? prev.map((m) => (m.id === msgId ? { ...m, content, ...opts } : m))
        : [...prev, { id: msgId, role, content, at: new Date().toISOString(), ...opts }],
    );
  }, []);

  // THE TWO REVIEWS, FROM THE PHONE. A new app waits for its requirements to be approved and
  // then for its product model; the web panel has a button for each, and the phone had neither,
  // so an app started on the phone could never be built from it (#36 review, 2026-11-13). The
  // open review is read from the server, as the web panel reads it.
  const [gate, setGate] = useState<Gate>(null);
  const [busy, setBusy] = useState(false);
  // Read when the chat opens and again whenever Smith has finished answering.
  useEffect(() => {
    if (busy) return;
    let alive = true;
    apiJson<{ gate?: Gate }>(`/api/projects/${projectId}/gates`)
      .then((g) => {
        if (alive) setGate(g.gate === 'requirements' || g.gate === 'product_model' ? g.gate : null);
      })
      .catch(() => {
        if (alive) setGate(null); // no Blueprint yet, or not reachable: nothing to approve
      });
    return () => {
      alive = false;
    };
  }, [projectId, busy]);

  const warmup = useCallback(async () => {
    try {
      const body = await postJson<{ blueprint?: unknown }>(`/api/projects/${projectId}/smith/warmup`);
      setHasBlueprint(Boolean(body?.blueprint));
    } catch {
      /* offline or refused: keep what we knew, so a built app is not sent to the new-app door */
    }
  }, [projectId]);

  // History and warmup, once per project.
  useEffect(() => {
    let alive = true;
    apiJson<HistoryRow[]>(`/api/projects/${projectId}/conversations`)
      .then((rows) => {
        if (!alive) return;
        setMessages(
          rows
            .filter((r) => r.content && !(r.role === 'user' && isControlSignal(r.content)))
            .map((r) => ({
              id: r.id,
              role: r.role,
              content: r.content,
              at: r.created_at ?? new Date().toISOString(),
            })),
        );
      })
      .catch(() => {});
    warmup();
    return () => {
      alive = false;
    };
  }, [projectId, warmup]);

  // Live events for the project. Smith's background messages (self-heal) and
  // office progress arrive here. Reconnects after a drop until we leave.
  useEffect(() => {
    let alive = true;
    const ctl = new AbortController();

    const onFrame = (frame: SseFrame) => {
      if (frame.event === 'self_heal_message') {
        const d = frame.data as { conversation_id?: string; role?: Msg['role']; content?: string };
        if (d.content) addMsg(d.role ?? 'assistant', d.content, d.conversation_id);
      } else if (frame.event === 'office') {
        const office = frame.data.office as
          | { message?: string; status?: string; action?: string }
          | undefined;
        const line = office?.message ?? office?.status ?? office?.action;
        if (line) setLiveStatus(line);
      }
    };

    (async () => {
      while (alive) {
        try {
          // The stream wants a short-lived ticket, fetched fresh for every connection.
          const { ticket } = await postJson<{ ticket: string }>(`/api/projects/${projectId}/stream-ticket`, {});
          await readSse(
            `/api/projects/${projectId}/events?ticket=${encodeURIComponent(ticket)}`,
            {},
            onFrame,
            ctl.signal,
          );
        } catch {
          /* dropped or refused: retry below */
        }
        if (alive) await sleep(3000);
      }
    })();

    return () => {
      alive = false;
      ctl.abort();
    };
  }, [projectId, addMsg]);

  // What Smith is doing right now, read from the project's job feed. It also tells a person
  // when their message waits behind a job that started earlier (one job at a time per project),
  // and shows a job someone else, or an earlier message, started.
  useEffect(() => {
    const ctl = new AbortController();
    let alive = true;

    // The agents at work now, by name. A turn ends with `agent_complete` and then one more
    // `agent_status` ("Done"): read as work, that last status put the spinner back for good after
    // every turn (#36 review, 2026-11-13). A status from an agent that has finished is not work
    // until it starts again; one from an agent we never saw start is a job we joined part way.
    // The line shows the most recent, and goes when none is left.
    const running = new Map<string, { text: string; since: number }>();
    const finished = new Set<string>();
    const show = () => {
      let latest: { text: string; since: number } | null = null;
      for (const w of running.values()) if (!latest || w.since >= latest.since) latest = w;
      setWork(latest ? { ...latest } : null);
    };
    const onFrame = (frame: SseFrame) => {
      if (frame.event !== 'office') return;
      const d = frame.data as { type?: string; status?: string; agent?: string };
      const who = String(d.agent ?? '');
      if (d.type === 'agent_start') {
        finished.delete(who);
        running.set(who, { text: 'Working on your message', since: Date.now() });
        show();
      } else if (d.type === 'agent_status' && d.status) {
        if (finished.has(who)) return;
        running.set(who, { text: String(d.status), since: running.get(who)?.since ?? Date.now() });
        show();
      } else if (d.type === 'agent_complete' || d.type === 'agent_error') {
        finished.add(who);
        running.delete(who);
        show();
      }
    };

    (async () => {
      let wait = 3000;
      while (alive) {
        try {
          await readSse(`/api/projects/${projectId}/office`, {}, onFrame, ctl.signal);
          wait = 3000;
        } catch (e) {
          // Not allowed or not found: nothing will change by asking again.
          if (e instanceof ApiError && (e.status === 403 || e.status === 404)) return;
        }
        if (alive) await sleep(wait);
        wait = Math.min(wait * 2, 30000);
      }
    })();

    return () => {
      alive = false;
      ctl.abort();
    };
  }, [projectId]);

  // Re-draw once a second while something runs, so the time on the banner moves.
  useEffect(() => {
    if (!busy && !work) return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [busy, work]);

  // Every message goes the way the web panel sends it: Smith decides whether it is a change,
  // a question or a first build, and the server saves both sides of the conversation. (The older
  // /smith/turn answers the same way but saves nothing, so a reload lost the person's message.)
  // We also send a short window of the chat so Smith can read its own earlier question.
  const smithChat = async (message: string, signal: AbortSignal, review?: { gate: Exclude<Gate, null> }) => {
    const history = messages
      .filter((m) => m.role !== 'system')
      .slice(-10)
      .map((m) => ({ role: m.role === 'assistant' ? 'smith' : 'user', text: m.content }));
    await readSse(
      `/api/projects/${projectId}/smith/chat`,
      {
        method: 'POST',
        // A review's yes is said as the web panel says it: approved, and which review it answers.
        body: { message, history, source: 'user', ...(review ? { approved: true, gate: review.gate, modules: null } : {}) },
      },
      (frame) => {
        const d = frame.data;
        switch (frame.event) {
          case 'message':
            addMsg('assistant', String(d.text ?? ''), undefined,
              Array.isArray(d.options) ? d.options.map((o) => String(o)).filter(Boolean) : undefined);
            break;
          case 'error':
            addMsg('system', String(d.message ?? d.detail ?? 'Something went wrong'));
            break;
        }
      },
      signal,
    );
    // A build may have changed the app, and may have created the Blueprint.
    onApplied();
    warmup();
  };

  // The ids of every message the server holds now, so a later poll can spot Smith's new answer.
  const knownIds = async () => {
    try {
      const rows = await apiJson<HistoryRow[]>(`/api/projects/${projectId}/conversations`);
      return new Set(rows.map((r) => r.id));
    } catch {
      return new Set<string>();
    }
  };

  // Polls the saved conversation until Smith's answer lands (up to 20 minutes).
  const followOnServer = async (baseline: Set<string>, signal: AbortSignal) => {
    const until = Date.now() + 20 * 60 * 1000;
    setLiveStatus('Smith is still working…');
    while (!signal.aborted && Date.now() < until) {
      await new Promise((r) => setTimeout(r, 6000));
      try {
        const rows = await apiJson<HistoryRow[]>(`/api/projects/${projectId}/conversations`);
        const fresh = rows.filter(
          (r) => r.role === 'assistant' && r.content && !baseline.has(r.id) && !isControlSignal(r.content),
        );
        if (fresh.length) {
          fresh.forEach((r) => addMsg('assistant', r.content, r.id));
          onApplied();
          warmup();
          return;
        }
      } catch {
        /* still offline: try again */
      }
    }
  };

  const send = async (raw: string, review?: { gate: Exclude<Gate, null> }) => {
    const message = raw.trim();
    if (!message || busy) return;
    const control = isControlSignal(message);
    if (!control) addMsg('user', message);
    setText('');
    setBusy(true);
    setLiveStatus(null);
    setSentAt(Date.now());

    const ctl = new AbortController();
    turnAbort.current = ctl;
    const baseline = await knownIds();
    try {
      await smithChat(message, ctl.signal, review);
    } catch (e) {
      if (ctl.signal.aborted) {
        /* we stopped waiting on purpose */
      } else if (isConnectionDrop(e)) {
        // A long job can outlive the phone's connection (screen lock, Wi-Fi hiccup). The
        // server keeps working, so ask it for the answer instead of showing an error.
        addMsg('system', 'The phone lost the connection. Smith keeps working on the server, and the answer will show here when it is ready.');
        await followOnServer(baseline, ctl.signal);
      } else {
        addMsg('system', e instanceof Error ? e.message : 'Something went wrong');
      }
    } finally {
      turnAbort.current = null;
      setBusy(false);
      setLiveStatus(null);
    }
  };

  // The last thing Smith said, when it offered choices and nothing has been said since.
  const last = messages[messages.length - 1];
  const offered = !busy && last?.role === 'assistant' ? last.options ?? [] : [];

  // Stops waiting on the phone. It does not stop work the server already began.
  const cancel = () => {
    turnAbort.current?.abort();
    addMsg('system', 'Stopped waiting. Smith may still finish on the server.');
  };

  const suggestions = hasBlueprint
    ? ['Make the main button green', 'Add a dark mode', 'Show a welcome message']
    : ['A habit tracker with streaks', 'A team task board', 'A booking page for my salon'];

  return (
    <View ref={root} style={styles.flex} onLayout={measureRoot}>
      <FlatList
        style={styles.flex}
        inverted
        data={[...messages].reverse()}
        keyExtractor={(m) => m.id}
        contentContainerStyle={{ paddingVertical: space.md, flexGrow: 1 }}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="interactive"
        ListEmptyComponent={
          <View style={[styles.emptyBox, { transform: [{ scaleY: -1 }] }]}>
            <Avatar who="smith" size={56} />
            <Text style={styles.emptyTitle}>
              {hasBlueprint ? 'What should Smith change?' : 'What do you want to build?'}
            </Text>
            <Text style={styles.emptyText}>
              {hasBlueprint
                ? 'Describe a change in plain words and Smith will apply it to your app.'
                : 'Describe your app and Smith will plan it and build it.'}
            </Text>
            <View style={styles.chips}>
              {suggestions.map((s) => (
                <Pressable
                  key={s}
                  onPress={() => setText(s)}
                  style={({ pressed }) => [styles.chip, pressed && { backgroundColor: colors.muted }]}>
                  <Feather name="zap" size={icon.sm - 2} color={colors.brand} />
                  <Text style={styles.chipText}>{s}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        }
        // In an inverted list the header sits at the bottom, above the input.
        ListHeaderComponent={
          <View style={{ gap: space.sm, paddingHorizontal: space.lg, paddingTop: space.sm }}>
            {busy || work ? (
              <View style={styles.working}>
                <ActivityIndicator size="small" color={colors.brand} />
                <Text style={styles.workingText} numberOfLines={4}>
                  {workingLine(work, busy, sentAt, liveStatus)}
                </Text>
              </View>
            ) : null}
            {offered.length ? <Offered options={offered} onPick={send} /> : null}
            {!busy && gate ? (
              <Button
                label={gate === 'requirements' ? 'Approve requirements' : 'Build app'}
                onPress={() => send(gate === 'requirements' ? 'Approve requirements' : 'Build app', { gate })}
                icon={(c) => <Feather name={gate === 'requirements' ? 'check' : 'play'} size={16} color={c} />}
              />
            ) : null}
          </View>
        }
        renderItem={({ item }) => <MessageRow msg={item} />}
      />

      <View style={[styles.composer, { paddingBottom: kbOverlap > 0 ? space.md : Math.max(insets.bottom, space.md) }]}>
        <View style={styles.inputBox}>
          <TextInput
            style={styles.input}
            placeholder={hasBlueprint ? 'Ask Smith to change the app…' : 'Describe your app…'}
            placeholderTextColor={colors.textTertiary}
            multiline
            value={text}
            onChangeText={setText}
            editable={!busy}
          />
          {busy ? (
            <Pressable
              style={[styles.sendBtn, { backgroundColor: colors.danger }]}
              onPress={cancel}
              hitSlop={6}
              accessibilityLabel="Stop">
              <Feather name="square" size={14} color="#fff" />
            </Pressable>
          ) : (
            <Pressable
              style={[styles.sendBtn, !text.trim() && { opacity: 0.35 }]}
              onPress={() => send(text)}
              disabled={!text.trim()}
              hitSlop={6}
              accessibilityLabel="Send">
              <Feather name="arrow-up" size={18} color={colors.primaryText} />
            </Pressable>
          )}
        </View>
      </View>
      {/* Pushes the composer up by exactly how much the keyboard covers this view. */}
      <View style={{ height: kbOverlap }} />
    </View>
  );
}

/** What Smith offered to do next, as buttons; a tap says it, as typing it would. */
function Offered({ options, onPick }: { options: string[]; onPick: (option: string) => void }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={styles.chips}>
      {options.map((o) => (
        <Pressable
          key={o}
          onPress={() => onPick(o)}
          accessibilityRole="button"
          style={({ pressed }) => [styles.chip, pressed && { backgroundColor: colors.muted }]}>
          <Feather name="corner-down-right" size={icon.sm - 2} color={colors.brand} />
          <Text style={styles.chipText}>{o}</Text>
        </Pressable>
      ))}
    </View>
  );
}

/** One message. Smith on the left with an avatar and a card bubble; you on the right in a filled bubble. */
function MessageRow({ msg }: { msg: Msg }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  if (msg.role === 'system') {
    return (
      <View style={styles.systemWrap}>
        <View style={styles.systemPill}>
          <Feather name="info" size={icon.sm - 2} color={colors.textSecondary} />
          <Text style={styles.systemText}>{msg.content}</Text>
        </View>
      </View>
    );
  }
  const time = new Date(msg.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (msg.role === 'user') {
    return (
      <View style={styles.userRow}>
        <View style={styles.userBubble}>
          <Text style={styles.userText}>{msg.content}</Text>
        </View>
        <Text style={styles.time}>{time}</Text>
      </View>
    );
  }
  return (
    <View style={styles.smithRow}>
      <Avatar who="smith" size={30} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={styles.nameLine}>
          <Text style={styles.name}>Smith</Text>
          <Text style={styles.time}>{time}</Text>
        </View>
        <View style={styles.smithBubble}>
          <Markdown>{msg.content}</Markdown>
        </View>
      </View>
    </View>
  );
}

const makeStyles = (colors: Palette) => StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.surfaceSecondary },
  emptyBox: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.sm, paddingHorizontal: space.xxl, paddingVertical: space.xxxl },
  emptyTitle: { ...type.title, color: colors.text, marginTop: space.md, textAlign: 'center' },
  emptyText: { ...type.callout, color: colors.textSecondary, textAlign: 'center', maxWidth: 300 },
  chips: { gap: space.sm, marginTop: space.lg, alignSelf: 'stretch' },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderRadius: radius.xl,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    ...shadow.card,
  },
  chipText: { ...type.callout, color: colors.text, flex: 1 },
  userRow: { alignItems: 'flex-end', paddingHorizontal: space.lg, paddingVertical: space.xs + 2, gap: 4 },
  userBubble: {
    maxWidth: '82%',
    backgroundColor: colors.primary,
    borderRadius: radius.xxl,
    borderBottomRightRadius: radius.sm,
    paddingHorizontal: space.md + 2,
    paddingVertical: space.sm + 2,
  },
  userText: { ...type.body, color: colors.primaryText },
  smithRow: { flexDirection: 'row', gap: space.sm + 2, paddingHorizontal: space.lg, paddingVertical: space.xs + 2 },
  nameLine: { flexDirection: 'row', alignItems: 'center', gap: space.sm, marginBottom: 4 },
  name: { ...type.caption, fontFamily: 'Inter_600SemiBold', color: colors.text },
  time: { ...type.caption, fontSize: 11, color: colors.textTertiary },
  smithBubble: {
    alignSelf: 'flex-start',
    maxWidth: '100%',
    backgroundColor: colors.surface,
    borderRadius: radius.xxl,
    borderTopLeftRadius: radius.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingHorizontal: space.md + 2,
    paddingVertical: space.sm + 2,
    ...shadow.card,
  },
  systemWrap: { alignItems: 'center', paddingHorizontal: space.lg, paddingVertical: space.sm },
  systemPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    maxWidth: '90%',
    backgroundColor: colors.muted,
    borderRadius: radius.pill,
    paddingHorizontal: space.md,
    paddingVertical: 6,
  },
  systemText: { ...type.caption, color: colors.textSecondary, textAlign: 'center', flexShrink: 1 },
  working: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm + 2,
    alignSelf: 'flex-start',
    maxWidth: '100%',
    paddingHorizontal: space.md + 2,
    paddingVertical: space.sm + 2,
    borderRadius: radius.pill,
    backgroundColor: colors.brandSoft,
  },
  workingText: { flexShrink: 1, ...type.callout, color: colors.brand },
  composer: { paddingHorizontal: space.md, paddingTop: space.sm, backgroundColor: colors.surfaceSecondary },
  inputBox: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: space.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: 26,
    backgroundColor: colors.surface,
    paddingLeft: space.lg + 2,
    paddingRight: 6,
    paddingVertical: 6,
    ...shadow.float,
  },
  // Same height as the send button (40) so one line of text, and the placeholder, sit in the middle.
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    paddingTop: 10,
    paddingBottom: 10,
    ...type.body,
    lineHeight: 20,
    textAlignVertical: 'center',
    color: colors.text,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
