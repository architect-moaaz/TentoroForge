"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CodeBlockPropsType } from "./CodeBlock.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface CodeBlockProps extends CodeBlockPropsType {
  style?: StyleSlotT;
}

export function CodeBlock({
  code = "",
  language,
  showCopy = true,
  className,
  style,
}: CodeBlockProps) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = () => {
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div
      data-code-block=""
      className={className}
      style={resolveStyle(style)}
      {...useMotion((style as StyleSlotT | undefined)?.motion)}
    >
      {(language || showCopy) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0.25rem 0.75rem",
            background: "#1e1e1e",
            borderBottom: "1px solid #333",
          }}
        >
          {language ? (
            <span
              style={{
                fontSize: "0.75rem",
                color: "#aaa",
                fontFamily: "monospace",
              }}
            >
              {language}
            </span>
          ) : (
            <span />
          )}
          {showCopy && (
            <button
              aria-label="Copy code"
              onClick={handleCopy}
              style={{
                background: "none",
                border: "1px solid #555",
                color: "#ccc",
                cursor: "pointer",
                borderRadius: "4px",
                padding: "2px 8px",
                fontSize: "0.75rem",
                fontFamily: "monospace",
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </div>
      )}
      <pre
        style={{
          margin: 0,
          padding: "1rem",
          background: "#1e1e1e",
          overflowX: "auto",
        }}
      >
        <code
          style={{
            fontFamily: "monospace",
            fontSize: "0.875rem",
            color: "#d4d4d4",
            whiteSpace: "pre",
          }}
        >
          {code}
        </code>
      </pre>
    </div>
  );
}
