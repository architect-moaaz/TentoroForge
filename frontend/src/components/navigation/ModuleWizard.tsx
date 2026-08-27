"use client";

import { useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  Package,
  ArrowRight,
  Pencil,
  Loader2,
  ChevronDown,
  ChevronRight,
  Link2,
  FileCode2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { useNavigationStore } from "@/stores/navigation";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ModuleResponse {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  description: string | null;
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

interface ModuleDetailResponse extends ModuleResponse {
  dependencies: DependencyResponse[];
  files: ModuleFileResponse[];
}

interface DependencyResponse {
  id: string;
  module_id: string;
  depends_on_id: string;
  dependency_type: string;
}

interface ModuleFileResponse {
  id: string;
  module_id: string;
  file_path: string;
  file_type: string;
}

interface ConnectionsResponse {
  nodes: { id: string; name: string; slug: string; file_count: number }[];
  edges: {
    id: string;
    source_module_id: string;
    target_module_id: string;
    dependency_type: string;
  }[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ModuleWizardProps {
  projectId: string;
}

export function ModuleWizard({ projectId }: ModuleWizardProps) {
  const queryClient = useQueryClient();
  const { setModules, setModuleDependencies } = useNavigationStore();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDepsOpen, setIsDepsOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Form state
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [editModule, setEditModule] = useState<ModuleResponse | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [depsModuleId, setDepsModuleId] = useState<string | null>(null);
  const [pendingDeps, setPendingDeps] = useState<
    { depends_on_id: string; dependency_type: string }[]
  >([]);

  // --- Queries ---

  const { data: modules = [], isLoading } = useQuery({
    queryKey: ["project", projectId, "db-modules"],
    queryFn: () =>
      api.get<ModuleResponse[]>(`/api/projects/${projectId}/modules`),
  });

  const { data: connections } = useQuery({
    queryKey: ["project", projectId, "module-connections"],
    queryFn: () =>
      api.get<ConnectionsResponse>(
        `/api/projects/${projectId}/modules/connections`,
      ),
    enabled: modules.length > 0,
  });

  const { data: expandedDetail } = useQuery({
    queryKey: ["project", projectId, "module-detail", expandedId],
    queryFn: () =>
      api.get<ModuleDetailResponse>(
        `/api/projects/${projectId}/modules/${expandedId}`,
      ),
    enabled: !!expandedId,
  });

  // --- Sync with navigation store ---

  const syncToStore = useCallback(
    (mods: ModuleResponse[], conns?: ConnectionsResponse) => {
      setModules(
        mods.map((m) => ({
          id: m.id,
          name: m.name,
          description: m.description || undefined,
          screens: [],
          createdAt: m.created_at,
        })),
      );
      if (conns) {
        setModuleDependencies(
          conns.edges.map((e) => ({
            id: e.id,
            sourceModuleId: e.source_module_id,
            targetModuleId: e.target_module_id,
            dependencyType: e.dependency_type as
              | "imports"
              | "navigates"
              | "shares_data",
          })),
        );
      }
    },
    [setModules, setModuleDependencies],
  );

  // --- Mutations ---

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "db-modules"],
    });
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "module-connections"],
    });
  }, [queryClient, projectId]);

  const createMutation = useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      api.post<ModuleResponse>(`/api/projects/${projectId}/modules`, body),
    onSuccess: () => {
      invalidate();
      setIsCreateOpen(false);
      setNewName("");
      setNewDescription("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: { name?: string; description?: string };
    }) =>
      api.put<ModuleResponse>(
        `/api/projects/${projectId}/modules/${id}`,
        body,
      ),
    onSuccess: () => {
      invalidate();
      setIsEditOpen(false);
      setEditModule(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api.delete(`/api/projects/${projectId}/modules/${id}`),
    onSuccess: () => invalidate(),
  });

  const updateDepsMutation = useMutation({
    mutationFn: ({
      moduleId,
      deps,
    }: {
      moduleId: string;
      deps: { depends_on_id: string; dependency_type: string }[];
    }) =>
      api.put<DependencyResponse[]>(
        `/api/projects/${projectId}/modules/${moduleId}/dependencies`,
        { dependencies: deps },
      ),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "module-detail"],
      });
      setIsDepsOpen(false);
      setDepsModuleId(null);
    },
  });

  // --- Handlers ---

  const openEdit = (mod: ModuleResponse) => {
    setEditModule(mod);
    setEditName(mod.name);
    setEditDescription(mod.description || "");
    setIsEditOpen(true);
  };

  const openDeps = (mod: ModuleResponse) => {
    setDepsModuleId(mod.id);
    // Load current deps
    const currentEdges =
      connections?.edges.filter((e) => e.source_module_id === mod.id) || [];
    setPendingDeps(
      currentEdges.map((e) => ({
        depends_on_id: e.target_module_id,
        dependency_type: e.dependency_type,
      })),
    );
    setIsDepsOpen(true);
  };

  const addPendingDep = () => {
    const available = modules.filter(
      (m) =>
        m.id !== depsModuleId &&
        !pendingDeps.some((d) => d.depends_on_id === m.id),
    );
    if (available.length > 0) {
      setPendingDeps([
        ...pendingDeps,
        { depends_on_id: available[0].id, dependency_type: "uses" },
      ]);
    }
  };

  const removePendingDep = (idx: number) => {
    setPendingDeps(pendingDeps.filter((_, i) => i !== idx));
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Modules</h3>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setIsCreateOpen(true)}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          New Module
        </Button>
      </div>

      {/* Module list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : modules.length === 0 ? (
        <div className="rounded-lg border border-dashed p-6 text-center">
          <Package className="mx-auto h-8 w-8 text-muted-foreground/50" />
          <p className="mt-2 text-sm text-muted-foreground">
            No modules yet. Create a module to organize your app into logical
            units.
          </p>
          <Button
            size="sm"
            className="mt-3"
            onClick={() => setIsCreateOpen(true)}
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            Create First Module
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          {modules.map((mod) => {
            const isExpanded = expandedId === mod.id;
            const depCount =
              connections?.edges.filter(
                (e) => e.source_module_id === mod.id,
              ).length || 0;
            const fileCount =
              connections?.nodes.find((n) => n.id === mod.id)?.file_count || 0;

            return (
              <div key={mod.id} className="rounded-lg border">
                {/* Module header */}
                <div
                  className="flex cursor-pointer items-center justify-between p-3"
                  onClick={() =>
                    setExpandedId(isExpanded ? null : mod.id)
                  }
                >
                  <div className="flex items-center gap-2">
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <Package className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">{mod.name}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {mod.slug}
                        {depCount > 0 && ` | ${depCount} dep${depCount > 1 ? "s" : ""}`}
                        {fileCount > 0 && ` | ${fileCount} file${fileCount > 1 ? "s" : ""}`}
                      </p>
                    </div>
                  </div>
                  <div
                    className="flex items-center gap-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      title="Edit dependencies"
                      onClick={() => openDeps(mod)}
                    >
                      <Link2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      title="Edit module"
                      onClick={() => openEdit(mod)}
                    >
                      <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      title="Delete module"
                      onClick={() => deleteMutation.mutate(mod.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </div>

                {/* Expanded detail */}
                {isExpanded && expandedDetail && (
                  <div className="border-t px-4 pb-3 pt-2 text-xs">
                    {mod.description && (
                      <p className="mb-2 text-muted-foreground">
                        {mod.description}
                      </p>
                    )}

                    {/* Dependencies */}
                    {expandedDetail.dependencies.length > 0 && (
                      <div className="mb-2">
                        <p className="mb-1 font-medium text-muted-foreground">
                          Dependencies
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {expandedDetail.dependencies.map((dep) => {
                            const target = modules.find(
                              (m) => m.id === dep.depends_on_id,
                            );
                            return (
                              <div
                                key={dep.id}
                                className="flex items-center gap-1"
                              >
                                <Badge
                                  variant="secondary"
                                  className="text-[10px]"
                                >
                                  {target?.name || "?"}
                                </Badge>
                                <span className="text-[10px] text-muted-foreground">
                                  ({dep.dependency_type})
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Files */}
                    {expandedDetail.files.length > 0 && (
                      <div>
                        <p className="mb-1 font-medium text-muted-foreground">
                          Files
                        </p>
                        <div className="space-y-0.5">
                          {expandedDetail.files.map((f) => (
                            <div
                              key={f.id}
                              className="flex items-center gap-1.5 text-[10px]"
                            >
                              <FileCode2 className="h-3 w-3 text-muted-foreground" />
                              <span className="font-mono">{f.file_path}</span>
                              <Badge
                                variant="outline"
                                className="text-[8px] px-1"
                              >
                                {f.file_type}
                              </Badge>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {expandedDetail.dependencies.length === 0 &&
                      expandedDetail.files.length === 0 && (
                        <p className="text-muted-foreground italic">
                          No dependencies or files assigned yet.
                        </p>
                      )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Connections summary */}
      {connections && connections.edges.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold mb-2">Dependency Graph</h4>
          <div className="space-y-1">
            {connections.edges.map((edge) => {
              const src = modules.find((m) => m.id === edge.source_module_id);
              const tgt = modules.find((m) => m.id === edge.target_module_id);
              return (
                <div
                  key={edge.id}
                  className="flex items-center gap-1 text-xs"
                >
                  <Badge variant="secondary" className="text-[10px]">
                    {src?.name || "?"}
                  </Badge>
                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                  <Badge variant="secondary" className="text-[10px]">
                    {tgt?.name || "?"}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground ml-1">
                    ({edge.dependency_type})
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* Create Module Dialog                                               */}
      {/* ================================================================= */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Module</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="mod-name">Name</Label>
              <Input
                id="mod-name"
                placeholder="e.g. User Management"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newName.trim()) {
                    createMutation.mutate({
                      name: newName.trim(),
                      description: newDescription.trim() || undefined,
                    });
                  }
                }}
              />
            </div>
            <div>
              <Label htmlFor="mod-desc">Description (optional)</Label>
              <Textarea
                id="mod-desc"
                placeholder="What does this module do?"
                rows={3}
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={() =>
                createMutation.mutate({
                  name: newName.trim(),
                  description: newDescription.trim() || undefined,
                })
              }
              disabled={!newName.trim() || createMutation.isPending}
            >
              {createMutation.isPending && (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ================================================================= */}
      {/* Edit Module Dialog                                                 */}
      {/* ================================================================= */}
      <Dialog open={isEditOpen} onOpenChange={setIsEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Module</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="edit-name">Name</Label>
              <Input
                id="edit-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="edit-desc">Description</Label>
              <Textarea
                id="edit-desc"
                rows={3}
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsEditOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!editModule) return;
                updateMutation.mutate({
                  id: editModule.id,
                  body: {
                    name: editName.trim() || undefined,
                    description: editDescription.trim() || undefined,
                  },
                });
              }}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending && (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              )}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ================================================================= */}
      {/* Edit Dependencies Dialog                                           */}
      {/* ================================================================= */}
      <Dialog open={isDepsOpen} onOpenChange={setIsDepsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Edit Dependencies
              {depsModuleId && (
                <span className="ml-1 text-sm font-normal text-muted-foreground">
                  — {modules.find((m) => m.id === depsModuleId)?.name}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {pendingDeps.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No dependencies. Click "Add" to create one.
              </p>
            ) : (
              pendingDeps.map((dep, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <Select
                    value={dep.depends_on_id}
                    onValueChange={(val) => {
                      const updated = [...pendingDeps];
                      updated[idx] = { ...updated[idx], depends_on_id: val };
                      setPendingDeps(updated);
                    }}
                  >
                    <SelectTrigger className="flex-1 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {modules
                        .filter((m) => m.id !== depsModuleId)
                        .map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                  <Select
                    value={dep.dependency_type}
                    onValueChange={(val) => {
                      const updated = [...pendingDeps];
                      updated[idx] = { ...updated[idx], dependency_type: val };
                      setPendingDeps(updated);
                    }}
                  >
                    <SelectTrigger className="w-28 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="uses">uses</SelectItem>
                      <SelectItem value="extends">extends</SelectItem>
                      <SelectItem value="imports">imports</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => removePendingDep(idx)}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={addPendingDep}
              disabled={
                pendingDeps.length >= modules.length - 1
              }
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add Dependency
            </Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDepsOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!depsModuleId) return;
                updateDepsMutation.mutate({
                  moduleId: depsModuleId,
                  deps: pendingDeps,
                });
              }}
              disabled={updateDepsMutation.isPending}
            >
              {updateDepsMutation.isPending && (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              )}
              Save Dependencies
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
