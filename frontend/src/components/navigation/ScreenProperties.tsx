"use client";

import { X, Home, AlertTriangle } from "lucide-react";
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
import { Separator } from "@/components/ui/separator";
import type { ScreenNodeData } from "@/types/navigation";

interface ScreenPropertiesProps {
  data: ScreenNodeData;
  onUpdate: (updates: Partial<ScreenNodeData>) => void;
  onClose: () => void;
  onSetDefault: () => void;
  onSetError: () => void;
}

export function ScreenProperties({
  data,
  onUpdate,
  onClose,
  onSetDefault,
  onSetError,
}: ScreenPropertiesProps) {
  return (
    <div className="flex w-[240px] shrink-0 flex-col border-l bg-white overflow-y-auto">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-xs font-semibold">Screen Properties</span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>

      <div className="space-y-4 p-3">
        <div>
          <Label className="text-xs">Name</Label>
          <Input
            className="mt-1 h-7 text-xs"
            value={data.label}
            onChange={(e) => onUpdate({ label: e.target.value })}
          />
        </div>

        <div>
          <Label className="text-xs">Route</Label>
          <Input
            className="mt-1 h-7 text-xs font-mono"
            value={data.route}
            onChange={(e) => onUpdate({ route: e.target.value })}
            placeholder="/dashboard"
          />
        </div>

        <div>
          <Label className="text-xs">Layout</Label>
          <Select
            value={data.layout || "blank"}
            onValueChange={(v) => onUpdate({ layout: v as ScreenNodeData["layout"] })}
          >
            <SelectTrigger className="mt-1 h-7 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sidebar" className="text-xs">Sidebar Layout</SelectItem>
              <SelectItem value="topnav" className="text-xs">Top Nav Layout</SelectItem>
              <SelectItem value="blank" className="text-xs">Blank</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Separator />

        <div className="space-y-2">
          <Button
            variant={data.isDefault ? "secondary" : "outline"}
            size="sm"
            className="w-full justify-start"
            onClick={onSetDefault}
          >
            <Home className="mr-1 h-3.5 w-3.5" />
            {data.isDefault ? "Default Screen" : "Set as Default"}
          </Button>
          <Button
            variant={data.isError ? "secondary" : "outline"}
            size="sm"
            className="w-full justify-start"
            onClick={onSetError}
          >
            <AlertTriangle className="mr-1 h-3.5 w-3.5" />
            {data.isError ? "Error Screen" : "Set as 404 Page"}
          </Button>
        </div>
      </div>
    </div>
  );
}
