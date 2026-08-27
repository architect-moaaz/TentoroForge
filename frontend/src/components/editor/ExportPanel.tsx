"use client";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface Props {
  projectId: string;
}

export function ExportPanel({ projectId }: Props) {
  const [open, setOpen] = useState(false);
  const url = `${API}/api/_debug/project-export/${projectId}`;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-xs px-3 py-1 rounded border bg-background hover:bg-muted"
      >
        Export
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-96 z-30 bg-popover border rounded-lg shadow-lg p-4 text-sm">
          <h4 className="font-semibold mb-1">Run locally</h4>
          <p className="text-muted-foreground mb-3">
            Download your generated app as a standalone Next.js project.
            Extract, install, and run.
          </p>
          <a
            href={url}
            download={`${projectId}.tar.gz`}
            className="inline-flex items-center px-3 py-1.5 rounded-md bg-primary text-primary-foreground"
            onClick={() => setOpen(false)}
          >
            Download {projectId}.tar.gz
          </a>
          <pre className="mt-4 bg-muted p-3 rounded text-xs overflow-x-auto whitespace-pre">
{`tar -xzf ${projectId}.tar.gz
cd ${projectId}
npm install
npm run dev
# open http://localhost:3000`}
          </pre>
        </div>
      )}
    </div>
  );
}
