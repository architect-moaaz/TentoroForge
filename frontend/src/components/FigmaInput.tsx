"use client";

import { useState, useEffect, FormEvent } from "react";
import { Figma, Key, Loader2, Sparkles } from "lucide-react";

interface FigmaInputProps {
  onGenerate: (figmaUrl: string, figmaToken: string) => void;
  isGenerating: boolean;
}

export function FigmaInput({ onGenerate, isGenerating }: FigmaInputProps) {
  const [figmaUrl, setFigmaUrl] = useState("");
  const [figmaToken, setFigmaToken] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);

  // Load saved token from localStorage
  useEffect(() => {
    const saved = localStorage.getItem("figma_token");
    if (saved) setFigmaToken(saved);
  }, []);

  // Save token to localStorage when changed
  useEffect(() => {
    if (figmaToken) {
      localStorage.setItem("figma_token", figmaToken);
    }
  }, [figmaToken]);

  const validateUrl = (url: string): boolean => {
    const pattern = /figma\.com\/(file|design)\/[a-zA-Z0-9]+/;
    return pattern.test(url);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!validateUrl(figmaUrl)) {
      setUrlError("Please enter a valid Figma URL (e.g., https://www.figma.com/design/...)");
      return;
    }
    if (!figmaToken.trim()) {
      return;
    }
    setUrlError(null);
    onGenerate(figmaUrl, figmaToken);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1.5 flex items-center gap-2 text-sm font-medium text-text-primary">
          <Figma className="h-4 w-4" />
          Figma URL
        </label>
        <input
          type="url"
          value={figmaUrl}
          onChange={(e) => {
            setFigmaUrl(e.target.value);
            setUrlError(null);
          }}
          placeholder="https://www.figma.com/design/abc123/My-Design"
          className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm transition-colors placeholder:text-text-tertiary focus:border-border-focus focus:outline-none focus:ring-2 focus:ring-brand-100"
          disabled={isGenerating}
        />
        {urlError && (
          <p className="mt-1 text-xs text-red-500">{urlError}</p>
        )}
      </div>

      <div>
        <label className="mb-1.5 flex items-center gap-2 text-sm font-medium text-text-primary">
          <Key className="h-4 w-4" />
          Figma Access Token
        </label>
        <input
          type="password"
          value={figmaToken}
          onChange={(e) => setFigmaToken(e.target.value)}
          placeholder="figd_xxxxxxxxxxxxx"
          className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm transition-colors placeholder:text-text-tertiary focus:border-border-focus focus:outline-none focus:ring-2 focus:ring-brand-100"
          disabled={isGenerating}
        />
        <p className="mt-1 text-xs text-text-tertiary">
          Generate at figma.com → Settings → Personal access tokens. Stored locally.
        </p>
      </div>

      <button
        type="submit"
        disabled={isGenerating || !figmaUrl || !figmaToken}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isGenerating ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Generating...
          </>
        ) : (
          <>
            <Sparkles className="h-4 w-4" />
            Generate Next.js App
          </>
        )}
      </button>
    </form>
  );
}
