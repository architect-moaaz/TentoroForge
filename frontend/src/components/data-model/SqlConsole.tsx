"use client";

import { useState, useCallback, useRef } from "react";
import { Play, Loader2, AlertCircle, Clock, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import Editor from "@monaco-editor/react";

interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
}

interface SqlConsoleProps {
  projectId: string;
  dbPort?: number | null;
}

export function SqlConsole({ projectId, dbPort }: SqlConsoleProps) {
  const [sql, setSql] = useState("SELECT * FROM ");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const editorRef = useRef<unknown>(null);

  const runQuery = useCallback(async () => {
    const query = sql.trim();
    if (!query) return;

    setIsRunning(true);
    setError(null);
    setResult(null);

    try {
      const normalized = query.toUpperCase();
      let data: QueryResult;

      if (normalized.startsWith("SELECT")) {
        data = await api.get<QueryResult>(
          `/api/projects/${projectId}/db/query?sql=${encodeURIComponent(query)}`,
        );
      } else {
        data = await api.post<QueryResult>(
          `/api/projects/${projectId}/db/query`,
          { sql: query },
        );
      }

      setResult(data);
      // Add to history
      setHistory((prev) => {
        const filtered = prev.filter((h) => h !== query);
        return [query, ...filtered].slice(0, 20);
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsRunning(false);
    }
  }, [sql, projectId]);

  const handleEditorMount = (editor: unknown) => {
    editorRef.current = editor;
    // Add Cmd+Enter keybinding
    const monacoEditor = editor as { addCommand: (keybinding: number, handler: () => void) => void };
    // KeyMod.CtrlCmd | KeyCode.Enter
    monacoEditor.addCommand(2048 | 3, () => {
      runQuery();
    });
  };

  if (!dbPort) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2">
        <AlertCircle className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          No database running — start preview first
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Editor toolbar */}
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <Button
          size="sm"
          onClick={runQuery}
          disabled={isRunning || !sql.trim()}
          className="h-7"
        >
          {isRunning ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Play className="mr-1 h-3 w-3" />
          )}
          Run
        </Button>
        <span className="text-[10px] text-muted-foreground">Cmd+Enter</span>

        {history.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="ml-auto h-7">
                <Clock className="mr-1 h-3 w-3" />
                History
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-60 overflow-y-auto">
              {history.map((h, i) => (
                <DropdownMenuItem
                  key={i}
                  className="font-mono text-xs"
                  onClick={() => setSql(h)}
                >
                  {h.length > 80 ? h.slice(0, 80) + "..." : h}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* SQL editor */}
      <div className="h-40 shrink-0 border-b">
        <Editor
          height="100%"
          defaultLanguage="sql"
          value={sql}
          onChange={(value) => setSql(value || "")}
          onMount={handleEditorMount}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: "off",
            scrollBeyondLastLine: false,
            wordWrap: "on",
            padding: { top: 8 },
            overviewRulerLanes: 0,
          }}
          theme="vs-light"
        />
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto">
        {error && (
          <div className="flex items-start gap-2 p-4 text-sm text-red-600">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <pre className="whitespace-pre-wrap font-mono text-xs">{error}</pre>
          </div>
        )}

        {result && result.rows.length > 0 && (
          <div>
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50">
                <tr>
                  {result.columns.map((col) => (
                    <th
                      key={col}
                      className="border-b px-3 py-2 text-left font-medium text-slate-600"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-slate-50/50">
                    {result.columns.map((col) => (
                      <td
                        key={col}
                        className="border-b px-3 py-1.5 font-mono text-slate-700"
                      >
                        {row[col] === null ? (
                          <span className="text-gray-400 italic">null</span>
                        ) : (
                          String(row[col])
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="border-t px-3 py-2 text-xs text-muted-foreground">
              {result.row_count} row{result.row_count !== 1 ? "s" : ""} returned
            </div>
          </div>
        )}

        {result && result.rows.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            Query returned no results
          </div>
        )}

        {!result && !error && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            Write a SQL query and press Run or Cmd+Enter
          </div>
        )}
      </div>
    </div>
  );
}
