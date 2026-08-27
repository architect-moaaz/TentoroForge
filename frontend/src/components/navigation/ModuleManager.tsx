"use client";

import { useState, useCallback } from "react";
import {
  Plus,
  Trash2,
  Package,
  ArrowRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useNavigationStore } from "@/stores/navigation";
import type { AppModule, ModuleDependencyEdge } from "@/types/navigation";

export function ModuleManager() {
  const { modules, setModules, moduleDependencies, setModuleDependencies } =
    useNavigationStore();
  const [newName, setNewName] = useState("");

  const addModule = useCallback(() => {
    if (!newName.trim()) return;
    const mod: AppModule = {
      id: `mod_${Date.now()}`,
      name: newName.trim(),
      screens: [],
      createdAt: new Date().toISOString(),
    };
    setModules([...modules, mod]);
    setNewName("");
  }, [newName, modules, setModules]);

  const removeModule = useCallback(
    (id: string) => {
      setModules(modules.filter((m) => m.id !== id));
      setModuleDependencies(
        moduleDependencies.filter(
          (d) => d.sourceModuleId !== id && d.targetModuleId !== id,
        ),
      );
    },
    [modules, setModules, moduleDependencies, setModuleDependencies],
  );

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Modules</h3>
      </div>

      {/* Add module */}
      <div className="flex gap-2">
        <Input
          className="h-8 text-xs flex-1"
          placeholder="Module name..."
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addModule()}
        />
        <Button size="sm" onClick={addModule} disabled={!newName.trim()}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          Add
        </Button>
      </div>

      {/* Module list */}
      {modules.length === 0 ? (
        <p className="text-center text-xs text-muted-foreground py-4">
          No modules defined. Modules help organize screens into logical groups.
        </p>
      ) : (
        <div className="space-y-2">
          {modules.map((mod) => (
            <div
              key={mod.id}
              className="flex items-center justify-between rounded-lg border p-3"
            >
              <div className="flex items-center gap-2">
                <Package className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium">{mod.name}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {mod.screens.length} screen
                    {mod.screens.length !== 1 ? "s" : ""}
                  </p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => removeModule(mod.id)}
              >
                <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Dependencies */}
      {modules.length >= 2 && (
        <>
          <h4 className="text-xs font-semibold mt-4">Dependencies</h4>
          {moduleDependencies.length === 0 ? (
            <p className="text-[10px] text-muted-foreground">
              Draw edges between modules on the canvas to define dependencies.
            </p>
          ) : (
            <div className="space-y-1">
              {moduleDependencies.map((dep) => {
                const src = modules.find((m) => m.id === dep.sourceModuleId);
                const tgt = modules.find((m) => m.id === dep.targetModuleId);
                return (
                  <div
                    key={dep.id}
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
                      ({dep.dependencyType})
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
