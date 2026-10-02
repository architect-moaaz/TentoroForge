"use client";

import { useState } from "react";

/**
 * A link inside an answer — and, for an export, the download itself.
 *
 * Smith answers "can I get all this out as a spreadsheet?" with a markdown
 * link to `/api/projects/<id>/exports/<file>`. That endpoint requires the
 * platform's Bearer token, and **a plain `<a href>` cannot carry one**, so a
 * click in a new tab would come back 401 and the owner would be told their
 * data was ready and handed nothing. The same problem, and the same fix, as
 * the source download in `ChatHistory`: fetch the blob with the token and
 * click a synthetic link.
 *
 * Only export URLs are intercepted. Every other link — a route in the app, a
 * docs page — renders as the anchor it is.
 */
const EXPORT_PATH = /^\/api\/projects\/[^/]+\/exports\/[^/]+$/;

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export function MarkdownLink({
  href,
  children,
  ...rest
}: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const isExport = !!href && EXPORT_PATH.test(href);

  if (!isExport) {
    return (
      <a href={href} {...rest}>
        {children}
      </a>
    );
  }

  const name = decodeURIComponent(href!.split("/").pop() || "export.csv");

  const download = async (e: React.MouseEvent) => {
    e.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const token =
        typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const resp = await fetch(`${API}${href}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(String(resp.status));
      const url = URL.createObjectURL(await resp.blob());
      const a = document.createElement("a");
      a.href = url;
      // A backup's URL is an opaque id; the server names the file it is.
      a.download =
        /filename="([^"]+)"/.exec(resp.headers.get("content-disposition") ?? "")?.[1] ?? name;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // SAID, NOT SWALLOWED. A download that silently does nothing reads as
      // "my data is gone"; the link stays clickable so it can be retried.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <a
      href={`${API}${href}`}
      onClick={download}
      aria-busy={busy}
      title={failed ? "That did not download — click to try again" : `Download ${name}`}
      className={failed ? "underline decoration-wavy" : undefined}
      {...rest}
    >
      {children}
      {busy ? " …" : ""}
    </a>
  );
}
