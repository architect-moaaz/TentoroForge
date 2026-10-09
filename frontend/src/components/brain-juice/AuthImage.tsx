"use client";

/**
 * A session file shown in the page: fetched with the person's token (an
 * `<img src>` cannot send one) and shown from a blob URL.
 */
import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

// One fetch per file per page: a screenshot shows in the conversation, on
// the board and enlarged, and each used to fetch it again.
const cache = new Map<string, Promise<string | null>>();

function load(path: string): Promise<string | null> {
  let got = cache.get(path);
  if (!got) {
    const token = localStorage.getItem("token");
    got = fetch(`${API_BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => (b ? URL.createObjectURL(b) : null))
      .catch(() => null);
    got.then((u) => { if (!u) cache.delete(path); });
    cache.set(path, got);
  }
  return got;
}

export function useFileUrl(path: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let gone = false;
    void load(path).then((u) => { if (!gone) setUrl(u); });
    return () => { gone = true; };
  }, [path]);
  return url;
}

export function AuthImage({ path, alt, className, onClick }:
  { path: string; alt: string; className?: string; onClick?: () => void }) {
  const url = useFileUrl(path);
  if (!url) return <div className={`animate-pulse bg-muted ${className ?? ""}`} aria-label={alt} />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={alt} className={className} onClick={onClick} />;
}
