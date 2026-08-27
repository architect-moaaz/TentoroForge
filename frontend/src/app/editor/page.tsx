"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type Project = { id: string; name: string };

export default function EditorIndexPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/projects")
      .then((r) => r.json())
      .then((data) => setProjects(Array.isArray(data) ? data : []))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ padding: 32, maxWidth: 720, margin: "0 auto" }}>
      <h1 style={{ fontSize: 24, marginBottom: 8, fontWeight: 600 }}>
        Schema Editor
      </h1>
      <p style={{ color: "#6b7280", marginBottom: 24, fontSize: 14 }}>
        Pick a project from{" "}
        <code
          style={{
            background: "#f4f4f5",
            padding: "1px 6px",
            borderRadius: 4,
            fontFamily: "monospace",
          }}
        >
          output/
        </code>{" "}
        to open the editor.
      </p>

      {loading && <p style={{ color: "#6b7280" }}>Loading projects…</p>}

      {!loading && projects.length === 0 && (
        <div
          style={{
            padding: 24,
            border: "1px dashed #d1d5db",
            borderRadius: 8,
            color: "#6b7280",
            fontSize: 14,
          }}
        >
          No projects found in{" "}
          <code
            style={{
              background: "#f4f4f5",
              padding: "1px 6px",
              borderRadius: 4,
            }}
          >
            output/
          </code>
          . Generate one first or place a foundation app there.
        </div>
      )}

      {!loading && projects.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {projects.map((p) => (
            <li key={p.id} style={{ marginBottom: 8 }}>
              <Link
                href={`/editor/${p.id}`}
                style={{
                  display: "block",
                  padding: "12px 16px",
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  textDecoration: "none",
                  color: "#111827",
                  transition: "border-color 0.15s",
                }}
              >
                <strong style={{ display: "block", marginBottom: 2 }}>
                  {p.name}
                </strong>
                <span style={{ fontSize: 12, color: "#6b7280" }}>
                  output/{p.id}/
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
