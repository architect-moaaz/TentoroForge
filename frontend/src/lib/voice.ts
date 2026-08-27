"use client";
// Voice module for the chat interface — browser-native Web Speech API, so it
// needs no external services or API keys and works in Chrome (the editor's
// target). Two hooks: speech-to-text (dictation) and text-to-speech (spoken
// replies), plus a helper that flattens markdown into speakable prose.

import { useCallback, useEffect, useRef, useState } from "react";

// ── Minimal Web Speech typings (absent from TS lib.dom in some setups) ──────
interface SRAlt { transcript: string }
interface SRResult { 0: SRAlt; isFinal: boolean }
interface SREvent { resultIndex: number; results: ArrayLike<SRResult> }
interface SRInstance {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onstart: (() => void) | null;
  onresult: ((e: SREvent) => void) | null;
  onerror: ((e: unknown) => void) | null;
  onend: (() => void) | null;
}
type SRCtor = new () => SRInstance;

function getSR(): SRCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Push-to-talk speech recognition. `continuous:false` so a natural pause ends
 * the utterance — which is what drives auto-send. `onInterim` streams the live
 * transcript (for a preview in the input); `onFinal` fires once with the
 * complete phrase when recognition ends.
 */
export function useSpeechRecognition(opts: {
  lang?: string;
  onInterim?: (text: string) => void;
  onFinal?: (text: string) => void;
}) {
  const { lang = "en-US", onInterim, onFinal } = opts;
  const [supported] = useState(getSR);
  const [listening, setListening] = useState(false);
  const recRef = useRef<SRInstance | null>(null);
  const finalRef = useRef("");
  // Always call the latest callbacks without re-creating start/stop.
  const interimCb = useRef(onInterim); interimCb.current = onInterim;
  const finalCb = useRef(onFinal); finalCb.current = onFinal;

  const stop = useCallback(() => {
    try { recRef.current?.stop(); } catch { /* not started */ }
  }, []);

  const start = useCallback(() => {
    const SR = getSR();
    if (!SR || recRef.current) return;
    const rec = new SR();
    rec.lang = lang;
    rec.continuous = false;
    rec.interimResults = true;
    finalRef.current = "";
    rec.onstart = () => setListening(true);
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalRef.current += r[0].transcript;
        else interim += r[0].transcript;
      }
      interimCb.current?.((finalRef.current + interim).trim());
    };
    rec.onerror = () => { /* onend still fires and cleans up */ };
    rec.onend = () => {
      setListening(false);
      recRef.current = null;
      const text = finalRef.current.trim();
      if (text) finalCb.current?.(text);
    };
    recRef.current = rec;
    try { rec.start(); } catch { recRef.current = null; setListening(false); }
  }, [lang]);

  const toggle = useCallback(() => {
    if (recRef.current) stop(); else start();
  }, [start, stop]);

  useEffect(() => () => { try { recRef.current?.abort(); } catch { /* noop */ } }, []);

  return { supported: !!supported, listening, start, stop, toggle };
}

/** Text-to-speech for assistant replies via SpeechSynthesis. */
export function useSpeechSynthesis() {
  const [supported] = useState(
    () => typeof window !== "undefined" && "speechSynthesis" in window,
  );
  const [speaking, setSpeaking] = useState(false);

  const cancel = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback((text: string) => {
    if (!supported || !text.trim()) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.02;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(u);
  }, [supported]);

  useEffect(() => () => { if (supported) window.speechSynthesis.cancel(); }, [supported]);

  return { supported, speaking, speak, cancel };
}

/** Flatten markdown/code into prose a TTS voice can read naturally, capped so a
 *  long reply doesn't monologue. */
export function stripForSpeech(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, ". code block. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^[\s]*[-*+]\s+/gm, "")
    .replace(/[#>*_~|]/g, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 1200);
}
