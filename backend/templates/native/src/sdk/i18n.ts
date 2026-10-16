// The app SDK (native) — the interface's language: one choice for the whole app,
// the web's `useT` / `useLanguage`. `config.generated.ts` lists the languages
// (`product.languages`) and the primary; every screen writes each string in
// every language: `t({ en: "Orders", hi: "ऑर्डर" })`. A plain string is shown
// as it is. The choice is kept in secure storage and announced to every
// mounted screen at once; `<LanguageSwitch />` (src/ui) is the one switch.
//
//   const t = useT();   t({ en: "Save", hi: "सहेजें" })

import * as React from "react";
import * as SecureStore from "expo-secure-store";
import { LANGUAGES, PRIMARY } from "../config.generated";
import { channel } from "./events";
import { knownLanguage, pick, type Text } from "./format";

export type { Text };

const KEY = "forge-lang";
const changed = channel<string>();
let current: string = PRIMARY;
let loaded = false;

/** The saved choice, read once; until then (and when nothing is saved) the primary. */
function load(): void {
  if (loaded) return;
  loaded = true;
  SecureStore.getItemAsync(KEY).then((saved) => {
    const tag = knownLanguage(saved, LANGUAGES);
    if (tag && tag !== current) { current = tag; changed.emit(tag); }
  }).catch(() => undefined);
}

function setLanguage(tag: string): void {
  const next = knownLanguage(tag, LANGUAGES) ?? PRIMARY;
  current = next;
  SecureStore.setItemAsync(KEY, next).catch(() => undefined);
  changed.emit(next);
}

export function useLanguage(): { lang: string; setLang: (tag: string) => void; languages: typeof LANGUAGES } {
  const [lang, setState] = React.useState<string>(current);
  React.useEffect(() => {
    load();
    setState(current);
    return changed.subscribe(setState);
  }, []);
  return { lang, setLang: setLanguage, languages: LANGUAGES };
}

/** `const t = useT(); t({ en: "Save", hi: "सहेजें" })` — the chosen language, else the primary, else any. */
export function useT(): (text: Text) => string {
  const { lang } = useLanguage();
  return React.useCallback((text: Text) => pick(text, lang, PRIMARY), [lang]);
}
