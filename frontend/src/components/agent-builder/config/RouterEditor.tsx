"use client";

import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { RouterConfig, RoutingStrategy, RouteDefinition } from "@/types/agent-builder";

interface RouterEditorProps {
  config: RouterConfig;
  onUpdate: (config: Partial<RouterConfig>) => void;
}

export function RouterEditor({ config, onUpdate }: RouterEditorProps) {
  const addRoute = () => {
    const routes = config.routes || [];
    onUpdate({
      routes: [
        ...routes,
        { id: `route_${Date.now()}`, label: "", condition: "" },
      ],
    });
  };

  const updateRoute = (index: number, updates: Partial<RouteDefinition>) => {
    const routes = [...(config.routes || [])];
    routes[index] = { ...routes[index], ...updates };
    onUpdate({ routes });
  };

  const removeRoute = (index: number) => {
    const routes = [...(config.routes || [])];
    routes.splice(index, 1);
    onUpdate({ routes });
  };

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Routing Strategy</Label>
        <Select
          value={config.strategy || "intent_classification"}
          onValueChange={(v) => onUpdate({ strategy: v as RoutingStrategy })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="intent_classification" className="text-xs">Intent Classification</SelectItem>
            <SelectItem value="condition" className="text-xs">Condition-Based</SelectItem>
            <SelectItem value="round_robin" className="text-xs">Round Robin</SelectItem>
            <SelectItem value="fallback" className="text-xs">Fallback Chain</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Route definitions */}
      <div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Routes</Label>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={addRoute}>
            <Plus className="h-3 w-3 mr-0.5" />
            Add Route
          </Button>
        </div>
        <div className="mt-1 space-y-2">
          {(config.routes || []).map((route, i) => (
            <div key={route.id} className="rounded border p-2 space-y-1.5">
              <div className="flex items-center gap-1">
                <Input
                  className="h-7 text-[10px] flex-1"
                  placeholder="Route label (e.g. billing)"
                  value={route.label}
                  onChange={(e) => updateRoute(i, { label: e.target.value })}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => removeRoute(i)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
              {config.strategy === "condition" && (
                <Input
                  className="h-7 text-[10px] font-mono"
                  placeholder="Condition expression..."
                  value={route.condition || ""}
                  onChange={(e) => updateRoute(i, { condition: e.target.value })}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <Label className="text-xs">Default Route</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="Fallback route label or node ID"
          value={config.default_route || ""}
          onChange={(e) => onUpdate({ default_route: e.target.value })}
        />
      </div>
    </div>
  );
}
