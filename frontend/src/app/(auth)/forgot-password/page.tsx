"use client";

import { useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AlertCircle, ArrowLeft, Loader2, Copy, Check } from "lucide-react";

type ForgotResponse = { message: string; reset_url?: string | null };

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ForgotResponse | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    setCopied(false);
    try {
      const res = await api.post<ForgotResponse>("/api/auth/forgot-password", { email });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed. Try again.");
    } finally {
      setLoading(false);
    }
  }

  async function copyLink() {
    if (!result?.reset_url) return;
    try {
      await navigator.clipboard.writeText(result.reset_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore clipboard failure */
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
          Reset your password
        </h1>
        <p className="mt-1.5 text-sm text-slate-500">
          Enter your email and we&apos;ll generate a reset link.
        </p>
      </div>

      {error && (
        <div className="mb-6 flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/50 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {!result && (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Email address
            </Label>
            <Input
              id="email"
              type="email"
              placeholder="you@company.com"
              className="h-11"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <Button type="submit" className="w-full h-11 text-sm font-medium" disabled={loading}>
            {loading ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Generating…</>
            ) : (
              "Send reset link"
            )}
          </Button>
        </form>
      )}

      {result && (
        <div className="space-y-4">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">
            {result.message}
          </div>
          {result.reset_url && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
              <div className="mb-2 font-medium">
                Email is not wired yet — copy this link and send it manually:
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded bg-white/60 px-2 py-1.5 font-mono text-[11px] text-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                  {result.reset_url}
                </code>
                <button
                  type="button"
                  onClick={copyLink}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-amber-300 bg-white hover:bg-amber-100 dark:border-amber-700 dark:bg-slate-900 dark:hover:bg-slate-800"
                  aria-label="Copy reset link"
                >
                  {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                </button>
              </div>
              <div className="mt-2 text-[11px] opacity-70">Link expires in 30 minutes.</div>
            </div>
          )}
          <Button
            variant="outline"
            className="w-full h-11 text-sm"
            onClick={() => { setResult(null); setEmail(""); }}
          >
            Send another
          </Button>
        </div>
      )}

      <p className="mt-6 text-center text-sm text-slate-500">
        <Link
          href="/login"
          className="inline-flex items-center gap-1 font-medium text-slate-700 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
        </Link>
      </p>
    </div>
  );
}
