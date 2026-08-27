import * as React from "react";

/**
 * Generic URL-state hook. Reads + writes a single key in the URL's search
 * params. Falls back gracefully outside browser environments (SSR — no-op).
 *
 * Usage:
 *   const [filter, setFilter] = useUrlState("filter", "active");
 *
 * The default value is used when the URL doesn't yet have the key. Setting
 * to the default removes the key from the URL (clean URLs).
 */
export function useUrlState(key: string, defaultValue: string = ""): [string, (next: string) => void] {
  const isClient = typeof window !== "undefined";
  const [value, setValue] = React.useState<string>(() => {
    if (!isClient) return defaultValue;
    const params = new URLSearchParams(window.location.search);
    return params.get(key) ?? defaultValue;
  });

  React.useEffect(() => {
    if (!isClient) return;
    const onPop = () => {
      const params = new URLSearchParams(window.location.search);
      setValue(params.get(key) ?? defaultValue);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [key, defaultValue, isClient]);

  const update = React.useCallback((next: string) => {
    setValue(next);
    if (!isClient) return;
    const params = new URLSearchParams(window.location.search);
    if (next === defaultValue || next === "") {
      params.delete(key);
    } else {
      params.set(key, next);
    }
    const newUrl = `${window.location.pathname}${params.toString() ? "?" + params.toString() : ""}${window.location.hash}`;
    window.history.replaceState({}, "", newUrl);
    // replaceState updates the address bar but never re-runs the server
    // component that resolved this page's dataSources — which is why every
    // filter chip changed the URL and nothing else. The host app listens for
    // this and refreshes; emitting an event keeps the library free of any
    // framework router dependency.
    window.dispatchEvent(new CustomEvent("forge:urlstate", { detail: { key, value: next } }));
  }, [key, defaultValue, isClient]);

  return [value, update];
}
