"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { FileTree } from "@/components/FileTree";
import { CodeEditor } from "./CodeEditor";

interface CodePanelProps {
  projectId: string;
}

export function CodePanel({ projectId }: CodePanelProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ["project", projectId, "files"],
    queryFn: () =>
      api.get<{ project_id: string; files: string[] }>(
        `/api/projects/${projectId}/files`,
      ),
  });

  const { data: fileContent, isLoading: contentLoading } = useQuery({
    queryKey: ["project", projectId, "file", selectedFile],
    queryFn: () =>
      api.get<{ path: string; content: string }>(
        `/api/projects/${projectId}/file?path=${encodeURIComponent(selectedFile!)}`,
      ),
    enabled: !!selectedFile,
  });

  const files = filesData?.files || [];

  return (
    <div className="flex h-full">
      {/* File tree sidebar */}
      <div className="w-64 shrink-0 overflow-y-auto border-r">
        {filesLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : files.length === 0 ? (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">
            No files generated yet
          </div>
        ) : (
          <FileTree
            files={files}
            selectedFile={selectedFile}
            onSelectFile={setSelectedFile}
          />
        )}
      </div>

      {/* Editor */}
      <div className="flex-1">
        {!selectedFile ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select a file to view its source code
          </div>
        ) : contentLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <CodeEditor
            content={fileContent?.content || ""}
            filePath={selectedFile}
          />
        )}
      </div>
    </div>
  );
}
