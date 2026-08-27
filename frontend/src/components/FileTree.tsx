"use client";

import {
  FileCode2,
  FileJson,
  FileType,
  Image,
  File,
  FolderOpen,
} from "lucide-react";

interface FileTreeProps {
  files: string[];
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
}

function getFileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "tsx":
    case "ts":
    case "jsx":
    case "js":
      return <FileCode2 className="h-4 w-4 text-blue-500" />;
    case "json":
      return <FileJson className="h-4 w-4 text-yellow-500" />;
    case "css":
      return <FileType className="h-4 w-4 text-purple-500" />;
    case "png":
    case "jpg":
    case "jpeg":
    case "svg":
    case "webp":
      return <Image className="h-4 w-4 text-green-500" />;
    default:
      return <File className="h-4 w-4 text-text-tertiary" />;
  }
}

interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  isFile: boolean;
}

function buildTree(files: string[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map(), isFile: false };

  for (const file of files) {
    const parts = file.split("/");
    let current = root;
    let currentPath = "";

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      const isLast = i === parts.length - 1;

      if (!current.children.has(part)) {
        current.children.set(part, {
          name: part,
          path: currentPath,
          children: new Map(),
          isFile: isLast,
        });
      }
      current = current.children.get(part)!;
    }
  }

  return root;
}

function TreeNodeView({
  node,
  selectedFile,
  onSelectFile,
  depth = 0,
}: {
  node: TreeNode;
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
  depth?: number;
}) {
  const children = Array.from(node.children.values()).sort((a, b) => {
    // Folders first, then alphabetical
    if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
    return a.name.localeCompare(b.name);
  });

  return (
    <>
      {children.map((child) => (
        <div key={child.path}>
          {child.isFile ? (
            <button
              onClick={() => onSelectFile(child.path)}
              className={`flex w-full items-center gap-2 px-3 py-1 text-left text-sm transition-colors hover:bg-surface-tertiary ${
                selectedFile === child.path
                  ? "bg-brand-50 text-brand-700"
                  : "text-text-secondary"
              }`}
              style={{ paddingLeft: `${depth * 16 + 12}px` }}
            >
              {getFileIcon(child.name)}
              <span className="truncate">{child.name}</span>
            </button>
          ) : (
            <>
              <div
                className="flex items-center gap-2 px-3 py-1 text-sm font-medium text-text-primary"
                style={{ paddingLeft: `${depth * 16 + 12}px` }}
              >
                <FolderOpen className="h-4 w-4 text-amber-500" />
                <span>{child.name}</span>
              </div>
              <TreeNodeView
                node={child}
                selectedFile={selectedFile}
                onSelectFile={onSelectFile}
                depth={depth + 1}
              />
            </>
          )}
        </div>
      ))}
    </>
  );
}

export function FileTree({ files, selectedFile, onSelectFile }: FileTreeProps) {
  const tree = buildTree(files);

  return (
    <div className="py-2">
      <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
        Generated Files
      </div>
      <TreeNodeView
        node={tree}
        selectedFile={selectedFile}
        onSelectFile={onSelectFile}
      />
    </div>
  );
}
