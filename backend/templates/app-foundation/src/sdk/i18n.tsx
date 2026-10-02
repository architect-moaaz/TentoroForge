"use client";
/**
 * The interface's language — one choice for the whole application.
 *
 * `@/lib/languages` is projected from the Blueprint (`product.locale` and
 * `product.languages`). The frame holds the one switch (`LanguageSwitch`);
 * every page reads the choice through `useT()` and writes each string in
 * every language: `t({ en: "Orders", hi: "ऑर्डर" })`. Before this, a page
 * that was asked for two languages rolled its own toggle, and no two pages
 * agreed (Test2, 2026-09-28).
 *
 * The choice is kept in a cookie (and browser storage, where it is allowed),
 * set on <html lang dir> so the script's font and the text direction follow,
 * and announced to every mounted page at once.
 */
import * as React from "react";
import { LANGUAGES, PRIMARY } from "@/lib/languages";

const COOKIE = "forge-lang";
const EVENT = "forge-lang-change";

export type Text = string | Record<string, string>;

function base(tag: string): string {
  return String(tag || "").replace("_", "-").split("-")[0].toLowerCase();
}

function known(tag: string | null | undefined): string | null {
  if (!tag) return null;
  const hit = LANGUAGES.find((l) => l.tag === tag) ?? LANGUAGES.find((l) => base(l.tag) === base(tag));
  return hit ? hit.tag : null;
}

function stored(): string | null {
  try {
    const m = document.cookie.match(new RegExp(`(?:^|; )${COOKIE}=([^;]*)`));
    if (m) return decodeURIComponent(m[1]);
  } catch { /* cookies refused */ }
  try {
    return window.localStorage.getItem(COOKIE);
  } catch {
    return null;
  }
}

function apply(tag: string): void {
  const lang = LANGUAGES.find((l) => l.tag === tag);
  document.documentElement.lang = tag;
  document.documentElement.dir = lang?.dir ?? "ltr";
}

/** The language a string is shown in: the chosen one, else the primary, else any. */
export function pick(text: Text, lang: string): string {
  if (typeof text === "string") return text;
  return text[lang] ?? text[base(lang)] ?? text[PRIMARY] ?? text[base(PRIMARY)] ?? Object.values(text)[0] ?? "";
}

export function useLanguage(): { lang: string; setLang: (tag: string) => void; languages: typeof LANGUAGES } {
  // The server and the first render agree on the primary language; the stored
  // choice is read after mount, so hydration never sees two texts.
  const [lang, setState] = React.useState<string>(PRIMARY);
  React.useEffect(() => {
    const chosen = known(stored());
    if (chosen && chosen !== PRIMARY) {
      setState(chosen);
      apply(chosen);
    }
    const on = (e: Event) => setState(String((e as CustomEvent).detail || PRIMARY));
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  const setLang = React.useCallback((tag: string) => {
    const next = known(tag) ?? PRIMARY;
    try {
      document.cookie = `${COOKIE}=${encodeURIComponent(next)}; path=/; max-age=31536000; samesite=lax`;
    } catch { /* cookies refused: this visit only */ }
    try {
      window.localStorage.setItem(COOKIE, next);
    } catch { /* storage refused */ }
    apply(next);
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next }));
  }, []);
  return { lang, setLang, languages: LANGUAGES };
}

/** `const t = useT(); t({ en: "Save", hi: "सहेजें" })` */
export function useT(): (text: Text) => string {
  const { lang } = useLanguage();
  return React.useCallback((text: Text) => pick(text, lang), [lang]);
}

function nameOf(tag: string): string {
  try {
    const own = new Intl.DisplayNames([tag], { type: "language" }).of(tag);
    if (own) return own.charAt(0).toLocaleUpperCase(tag) + own.slice(1);
  } catch { /* an engine without DisplayNames */ }
  return tag.toUpperCase();
}

/** The application's one language switch. Nothing when there is one language. */
export function LanguageSwitch({ className }: { className?: string }) {
  const { lang, setLang, languages } = useLanguage();
  if (languages.length < 2) return null;
  return (
    <div role="group" aria-label="Language" className={["inline-flex items-center gap-0.5 rounded-md border border-border p-0.5", className].filter(Boolean).join(" ")}>
      {languages.map((l) => (
        <button
          key={l.tag}
          type="button"
          lang={l.tag}
          dir={l.dir}
          aria-pressed={l.tag === lang}
          onClick={() => setLang(l.tag)}
          className={
            "rounded px-2 py-1 text-xs font-medium transition-colors "
            + (l.tag === lang ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted")
          }
        >
          {nameOf(l.tag)}
        </button>
      ))}
    </div>
  );
}
