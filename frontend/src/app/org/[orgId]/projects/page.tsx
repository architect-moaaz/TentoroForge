"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2, FolderOpen, MoreVertical, Copy, Trash2, Pencil } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { NewAppDialog } from "@/components/projects/NewAppDialog";
import { DeleteProjectDialog } from "@/components/projects/DeleteProjectDialog";
import type { Project } from "@/types/project";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  generating: "bg-blue-100 text-blue-700",
  ready: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
};

function ProjectsPage({ orgId }: { orgId: string }) {
  const [showNewApp, setShowNewApp] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [copyingId, setCopyingId] = useState<string | null>(null);
  // BUG-007: let users rename a project (esp. after duplicating).
  const [renameTarget, setRenameTarget] = useState<Project | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renaming, setRenaming] = useState(false);
  const queryClient = useQueryClient();

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["org", orgId, "projects"],
    queryFn: () => api.get<Project[]>(`/api/orgs/${orgId}/projects`),
  });

  const handleCopy = async (project: Project) => {
    setCopyingId(project.id);
    try {
      await api.post(`/api/projects/${project.id}/copy`);
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
    } finally {
      setCopyingId(null);
    }
  };

  const handleRename = async () => {
    const name = renameValue.trim();
    if (!renameTarget || !name || name === renameTarget.name) {
      setRenameTarget(null);
      return;
    }
    setRenaming(true);
    try {
      await api.put(`/api/projects/${renameTarget.id}`, { name });
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      setRenameTarget(null);
    } finally {
      setRenaming(false);
    }
  };

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Projects</h1>
        <Button onClick={() => setShowNewApp(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New App
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
          <FolderOpen className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="mb-2 text-lg font-medium">No projects yet</p>
          <p className="mb-4 text-sm text-muted-foreground">
            Create your first app by describing what you need
          </p>
          <Button onClick={() => setShowNewApp(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New App
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <div key={project.id} className="relative">
              <Link href={`/org/${orgId}/projects/${project.id}`}>
                <Card className="transition-shadow hover:shadow-md">
                  <CardHeader>
                    {/* BUG-006 + BUG-008: the status badge used to sit in the
                        top-right, where it overlapped the ⋮ action button (by
                        ~15px) and the menu's dropdown. Keep that corner clear for
                        the ⋮ (title reserves space with pr-8) and move the badge
                        to the bottom row beside the date. */}
                    <CardTitle className="text-base pr-8">
                      {project.name}
                    </CardTitle>
                    <CardDescription className="line-clamp-2">
                      {project.description || "No description"}
                    </CardDescription>
                    <div className="flex items-center justify-between gap-2 pt-1">
                      <p className="text-xs text-muted-foreground">
                        {new Date(project.created_at).toLocaleDateString()}
                      </p>
                      <Badge
                        variant="secondary"
                        className={STATUS_COLORS[project.status] || ""}
                      >
                        {project.status}
                      </Badge>
                    </div>
                  </CardHeader>
                </Card>
              </Link>

              {/* Context menu */}
              <div className="absolute right-2 top-2 z-10">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={(e) => e.preventDefault()}
                    >
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.preventDefault();
                        setRenameTarget(project);
                        setRenameValue(project.name);
                      }}
                    >
                      <Pencil className="mr-2 h-4 w-4" />
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.preventDefault();
                        handleCopy(project);
                      }}
                      disabled={copyingId === project.id}
                    >
                      {copyingId === project.id ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Copy className="mr-2 h-4 w-4" />
                      )}
                      Duplicate
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onClick={(e) => {
                        e.preventDefault();
                        setDeleteTarget(project);
                      }}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          ))}
        </div>
      )}

      <NewAppDialog
        orgId={orgId}
        open={showNewApp}
        onOpenChange={setShowNewApp}
      />

      {deleteTarget && (
        <DeleteProjectDialog
          open={!!deleteTarget}
          onOpenChange={(open) => !open && setDeleteTarget(null)}
          projectId={deleteTarget.id}
          projectName={deleteTarget.name}
          onDeleted={() => {
            setDeleteTarget(null);
            queryClient.invalidateQueries({
              queryKey: ["org", orgId, "projects"],
            });
          }}
        />
      )}

      {/* BUG-007: rename dialog */}
      <Dialog
        open={!!renameTarget}
        onOpenChange={(open) => !open && setRenameTarget(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Rename project</DialogTitle>
          </DialogHeader>
          <Input
            autoFocus
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRename();
            }}
            placeholder="Project name"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRenameTarget(null)}>
              Cancel
            </Button>
            <Button
              onClick={handleRename}
              disabled={renaming || !renameValue.trim()}
            >
              {renaming && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function ProjectsPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <ProjectsPage orgId={orgId} />;
}
