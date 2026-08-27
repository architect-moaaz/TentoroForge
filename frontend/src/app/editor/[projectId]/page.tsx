"use client";
import { use } from "react";
import { VisualEditorWorkspace } from "@/components/visual-editor/VisualEditorWorkspace";

export default function EditorPage({
  params,
}: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return (
    <div className="h-screen">
      <VisualEditorWorkspace projectId={projectId} />
    </div>
  );
}
