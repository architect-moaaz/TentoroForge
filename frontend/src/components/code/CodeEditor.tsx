"use client";

import { useMemo } from "react";
import Editor from "@monaco-editor/react";

interface CodeEditorProps {
  content: string;
  filePath: string;
  readOnly?: boolean;
}

function getLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase();
  const langMap: Record<string, string> = {
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    css: "css",
    html: "html",
    md: "markdown",
    sql: "sql",
    yaml: "yaml",
    yml: "yaml",
    env: "plaintext",
    mjs: "javascript",
  };
  return langMap[ext || ""] || "plaintext";
}

export function CodeEditor({
  content,
  filePath,
  readOnly = true,
}: CodeEditorProps) {
  const language = useMemo(() => getLanguage(filePath), [filePath]);

  return (
    <Editor
      height="100%"
      language={language}
      value={content}
      theme="vs-dark"
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 13,
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        wordWrap: "on",
        padding: { top: 8 },
      }}
    />
  );
}
