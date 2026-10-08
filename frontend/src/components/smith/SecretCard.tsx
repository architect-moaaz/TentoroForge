"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import type { SecretField } from "@/hooks/useBlueprintRun";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

/**
 * A key Smith needs, typed in the chat and never sent as a chat message.
 *
 * The conversation is stored and replayed, so a key typed as a message would sit in the
 * transcript. This field sends it to the same row Settings → Integrations writes
 * (`PUT /api/orgs/{org}/integrations`), where it is encrypted with the organisation's other
 * keys, and tells Smith only that it was saved. The value lives in this component's state
 * until the request is made and is cleared once it is; nothing here logs or echoes it.
 */
export function SecretCard({
  field,
  disabled,
  onSaved,
}: {
  field: SecretField;
  disabled?: boolean;
  /** Told once the key is stored; sends the field's `saved` words as the next turn. */
  onSaved: (said: string) => void;
}) {
  const params = useParams<{ orgId?: string }>();
  const orgId = params?.orgId;
  const [value, setValue] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState("");

  const save = async () => {
    const typed = value.trim();
    if (!typed || state === "saving" || state === "saved") return;
    if (!orgId) {
      setState("error");
      setError("Open this project from its organisation to save the key, or add it under Settings → Integrations.");
      return;
    }
    setState("saving");
    setError("");
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const res = await fetch(`${API_BASE}/api/orgs/${orgId}/integrations`, {
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ provider: field.provider, key: field.key, value: typed }),
      });
      if (!res.ok) {
        // The server's own reason, when it gives one: a platform that cannot encrypt a key
        // (no master secret configured) answers with exactly that, and "could not be saved"
        // sends the person to retry something that cannot work.
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        const detail = typeof body?.detail === "string" ? body.detail.trim() : "";
        setState("error");
        setError(
          res.status === 403
            ? "Only an organisation admin can save integration keys. Ask an admin, or build with the Forge UI Designer instead."
            : detail && detail.length < 300
              ? `The key could not be saved: ${detail} You can build with the Forge UI Designer instead.`
              : "The key could not be saved. Check it and try again, or add it under Settings → Integrations.",
        );
        return;
      }
      setValue("");
      setState("saved");
      onSaved(field.saved);
    } catch {
      setState("error");
      setError("Could not reach the server. Try again in a moment.");
    }
  };

  if (state === "saved") {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5" /> {field.label} saved.
      </p>
    );
  }

  return (
    <form
      className="mt-2 space-y-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <label htmlFor={`secret-${field.key}`} className="flex items-center gap-1.5 text-xs font-medium">
        <KeyRound className="h-3.5 w-3.5" /> {field.label}
      </label>
      <div className="flex gap-1.5">
        <input
          id={`secret-${field.key}`}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          disabled={disabled || state === "saving"}
          onChange={(e) => setValue(e.target.value)}
          placeholder={field.placeholder ?? ""}
          className="h-8 min-w-0 flex-1 rounded border border-current/25 bg-background px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim() || state === "saving"}
          className="inline-flex h-8 items-center gap-1.5 rounded bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {state === "saving" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Save key
        </button>
      </div>
      {state === "error" && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}
