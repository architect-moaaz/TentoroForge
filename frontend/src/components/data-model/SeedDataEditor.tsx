"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Sprout,
  Loader2,
  Play,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Editor from "@monaco-editor/react";
import { SchemaChangeProgress } from "./SchemaChangeProgress";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface SeedDataEditorProps {
  projectId: string;
  onComplete?: () => void;
}

export function SeedDataEditor({ projectId, onComplete }: SeedDataEditorProps) {
  const [rowCount, setRowCount] = useState(10);
  const [theme, setTheme] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState({
    status: null as string | null,
    logs: [] as string[],
    filesChanged: [] as string[],
    toolCalls: [] as { tool: string; args: string }[],
  });
  const [error, setError] = useState<string | null>(null);

  // Load existing seed.ts
  const { data: seedFile } = useQuery({
    queryKey: ["project", projectId, "file", "src/db/seed.ts"],
    queryFn: () =>
      api.get<{ path: string; content: string }>(
        `/api/projects/${projectId}/file?path=${encodeURIComponent("src/db/seed.ts")}`,
      ),
  });

  const handleGenerate = async () => {
    setIsGenerating(true);
    setProgress({ status: null, logs: [], filesChanged: [], toolCalls: [] });
    setError(null);

    try {
      const token =
        typeof window !== "undefined" ? localStorage.getItem("token") : null;

      const response = await fetch(
        `${API_BASE}/api/projects/${projectId}/db/seed`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            row_count: rowCount,
            theme: theme || null,
          }),
        },
      );

      if (!response.ok) {
        const err = await response.json().catch(() => ({
          detail: response.statusText,
        }));
        throw new Error(err.detail || "Failed to generate seed data");
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            if (dataStr && currentEvent) {
              try {
                const data = JSON.parse(dataStr);
                setProgress((prev) => {
                  const next = { ...prev };
                  switch (currentEvent) {
                    case "status":
                      next.status = data.message;
                      break;
                    case "log":
                      next.logs = [...prev.logs, data.text];
                      break;
                    case "file_created":
                      next.filesChanged = [...prev.filesChanged, data.path];
                      break;
                    case "tool_call":
                      next.toolCalls = [
                        ...prev.toolCalls,
                        { tool: data.tool, args: data.args },
                      ];
                      break;
                    case "complete":
                      onComplete?.();
                      break;
                    case "error":
                      setError(data.message);
                      break;
                  }
                  return next;
                });
              } catch {
                // Skip malformed JSON
              }
            }
          }
        }
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Controls */}
      <div className="flex items-end gap-4 border-b px-4 py-3">
        <div>
          <Label className="mb-1 text-xs">Rows per table</Label>
          <Input
            type="number"
            min={1}
            max={100}
            value={rowCount}
            onChange={(e) => setRowCount(Number(e.target.value))}
            className="h-8 w-24 text-sm"
          />
        </div>
        <div className="flex-1">
          <Label className="mb-1 text-xs">Theme (optional)</Label>
          <Input
            placeholder="e.g. e-commerce, social media, healthcare"
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            className="h-8 text-sm"
          />
        </div>
        <Button
          size="sm"
          onClick={handleGenerate}
          disabled={isGenerating}
          className="h-8"
        >
          {isGenerating ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Sprout className="mr-1 h-3 w-3" />
          )}
          Generate Realistic Data
        </Button>
      </div>

      {/* Progress overlay */}
      {isGenerating && (
        <div className="border-b bg-slate-50 p-3">
          <SchemaChangeProgress
            isApplying={isGenerating}
            status={progress.status}
            filesChanged={progress.filesChanged}
            toolCalls={progress.toolCalls}
            error={error}
          />
        </div>
      )}

      {error && !isGenerating && (
        <div className="flex items-start gap-2 border-b bg-red-50 px-4 py-2">
          <AlertCircle className="mt-0.5 h-4 w-4 text-red-500" />
          <p className="text-xs text-red-600">{error}</p>
        </div>
      )}

      {/* Seed file viewer */}
      <div className="flex-1">
        {seedFile?.content ? (
          <Editor
            height="100%"
            defaultLanguage="typescript"
            value={seedFile.content}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 13,
              scrollBeyondLastLine: false,
              wordWrap: "on",
              padding: { top: 8 },
            }}
            theme="vs-light"
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <Sprout className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No seed file yet — click "Generate Realistic Data" to create one
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
