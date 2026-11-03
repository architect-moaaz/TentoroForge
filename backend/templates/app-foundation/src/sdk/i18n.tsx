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

// THE DESIGN'S OWN WORDS. A drawn screen (`services/drawn`) shows its words as
// they were drawn, in the language they were drawn in: the DITANS sidebar,
// headings and labels stayed English when the person chose Arabic
// (wzml1sa6, 2026-10-31). `product.words` holds them in each other language,
// projected to `public/words/<tag>.json`; `DrawnWords` shows every text of the
// page in the chosen language — each text, and each attribute read aloud or
// shown as a hint, is looked up as it is and again whenever the page changes
// it, and put back as drawn when the person switches back. A text the table
// does not hold (a name, a number, what a record says) is left as it is, and
// so is anything marked `translate="no"`.
const SPOKEN = ["placeholder", "title", "alt", "aria-label"];
const SKIP = "script,style,textarea,code,pre,[translate='no'],[contenteditable='true']";
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
const tables: Record<string, Promise<Record<string, string>>> = {};

function wordTable(tag: string): Promise<Record<string, string>> {
  // A table that could not be read is asked for again next time, not kept empty.
  const failed = () => { delete tables[tag]; return {}; };
  return (tables[tag] ??= fetch(`${BASE_PATH}/words/${encodeURIComponent(tag)}.json`)
    .then((r) => (r.ok ? r.json() : r.status === 404 ? {} : failed()))
    .catch(failed));
}

const squeeze = (s: string) => s.replace(/\s+/g, " ").trim();
// What a node said before it was given another language, and what it was given.
const drawnText = new WeakMap<Node, [string, string]>();
const drawnAttr = new WeakMap<Element, Record<string, [string, string]>>();

function said(drawn: string, words: Record<string, string> | null): string | null {
  const hit = words?.[squeeze(drawn)];
  if (!hit) return null;
  return (drawn.match(/^\s*/)?.[0] ?? "") + hit + (drawn.match(/\s*$/)?.[0] ?? "");
}

// React has not hydrated a streamed part yet: changing its text now would make
// it disagree with what the server sent. It is looked at again once it has.
function hydrated(el: Element | null): boolean {
  return !!el && Object.keys(el).some((k) => k.startsWith("__reactFiber$"));
}

function sayText(node: Node, words: Record<string, string> | null): void {
  const now = node.nodeValue ?? "";
  const kept = drawnText.get(node);
  const drawn = kept && now === kept[1] ? kept[0] : now;
  const next = said(drawn, words);
  if (next !== null) {
    drawnText.set(node, [drawn, next]);
    if (now !== next) node.nodeValue = next;
  } else if (kept && now === kept[1]) {
    drawnText.delete(node);
    node.nodeValue = drawn;
  }
}

function sayAttrs(el: Element, words: Record<string, string> | null): void {
  for (const name of SPOKEN) {
    const now = el.getAttribute(name);
    if (now === null) continue;
    const kept = drawnAttr.get(el)?.[name];
    const drawn = kept && now === kept[1] ? kept[0] : now;
    const next = said(drawn, words);
    const all = drawnAttr.get(el) ?? {};
    if (next !== null) {
      all[name] = [drawn, next];
      drawnAttr.set(el, all);
      if (now !== next) el.setAttribute(name, next);
    } else if (kept && now === kept[1]) {
      delete all[name];
      el.setAttribute(name, drawn);
    }
  }
}

/** True when part of the page was not hydrated yet and is to be looked at again. */
function sayAll(root: Element, words: Record<string, string> | null): boolean {
  let waiting = false;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => n.nodeType === Node.ELEMENT_NODE && (n as Element).matches(SKIP)
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  for (let n: Node | null = walker.currentNode; n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      if (hydrated(n.parentElement)) sayText(n, words);
      else if (n.nodeValue?.trim()) waiting = true;
    } else if (hydrated(n as Element)) {
      sayAttrs(n as Element, words);
    }
  }
  return waiting;
}

/** Every text of the page in the chosen language, from the design's word table. */
export function DrawnWords() {
  const { lang } = useLanguage();
  React.useEffect(() => {
    let words: Record<string, string> | null = null;
    let live = true;
    let queued = 0;
    let waits = 0;   // half-second looks at a page still hydrating: 30s at most
    const again = (ms = 30) => {
      if (queued) return;
      queued = window.setTimeout(() => {
        queued = 0;
        // A part streamed in is hydrated without changing the page, so nothing
        // says when it is ready: while some is not, look again.
        if (live && sayAll(document.body, words) && ++waits < 60) again(500);
      }, ms);
    };
    const watch = new MutationObserver(() => again());
    (lang === PRIMARY ? Promise.resolve(null) : wordTable(lang)).then((table) => {
      if (!live) return;
      words = table && Object.keys(table).length ? table : null;
      if (sayAll(document.body, words)) again(500);
      watch.observe(document.body, { subtree: true, childList: true, characterData: true,
                                     attributes: true, attributeFilter: SPOKEN });
    });
    return () => {
      live = false;
      watch.disconnect();
      if (queued) window.clearTimeout(queued);
    };
  }, [lang]);
  return null;
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
