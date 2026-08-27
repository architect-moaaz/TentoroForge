"use client";

import { useState, useCallback } from "react";
import { Highlight, themes } from "prism-react-renderer";
import { Copy, Check } from "lucide-react";

interface CodePreviewProps {
  filePath: string;
  content: string;
}

function getLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "tsx":
    case "ts":
      return "tsx";
    case "jsx":
    case "js":
    case "mjs":
      return "jsx";
    case "json":
      return "json";
    case "css":
      return "css";
    case "html":
      return "markup";
    case "md":
      return "markdown";
    default:
      return "plaintext";
  }
}

export function CodePreview({ filePath, content }: CodePreviewProps) {
  const [copied, setCopied] = useState(false);
  const language = getLanguage(filePath);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [content]);

  return (
    <div className="flex h-full flex-col">
      {/* File header */}
      <div className="flex items-center justify-between border-b border-border bg-surface px-4 py-2">
        <span className="font-mono text-sm text-text-secondary">
          {filePath}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-tertiary transition-colors hover:bg-surface-tertiary hover:text-text-secondary"
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-green-500" />
              Copied
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" />
              Copy
            </>
          )}
        </button>
      </div>

      {/* Code content */}
      <div className="flex-1 overflow-auto custom-scrollbar">
        <Highlight theme={themes.vsLight} code={content} language={language}>
          {({ style, tokens, getLineProps, getTokenProps }) => (
            <pre
              className="p-4 text-sm leading-relaxed"
              style={{ ...style, background: "transparent", margin: 0 }}
            >
              {tokens.map((line, i) => (
                <div key={i} {...getLineProps({ line })} className="table-row">
                  <span className="table-cell select-none pr-4 text-right text-xs text-text-tertiary">
                    {i + 1}
                  </span>
                  <span className="table-cell">
                    {line.map((token, key) => (
                      <span key={key} {...getTokenProps({ token })} />
                    ))}
                  </span>
                </div>
              ))}
            </pre>
          )}
        </Highlight>
      </div>
    </div>
  );
}
