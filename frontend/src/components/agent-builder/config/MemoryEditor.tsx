"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { MemoryConfig, MemoryType } from "@/types/agent-builder";

interface MemoryEditorProps {
  config: MemoryConfig;
  onUpdate: (config: Partial<MemoryConfig>) => void;
}

export function MemoryEditor({ config, onUpdate }: MemoryEditorProps) {
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Memory Type</Label>
        <Select
          value={config.memory_type || "conversation"}
          onValueChange={(v) => onUpdate({ memory_type: v as MemoryType })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="conversation" className="text-xs">Conversation History</SelectItem>
            <SelectItem value="vector" className="text-xs">Vector Store</SelectItem>
            <SelectItem value="key_value" className="text-xs">Key-Value Store</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label className="text-xs">
          Capacity {config.memory_type === "conversation" ? "(max messages)" : "(max entries)"}
        </Label>
        <Input
          className="mt-1 h-8 text-xs"
          type="number"
          placeholder="100"
          value={config.capacity || ""}
          onChange={(e) =>
            onUpdate({ capacity: e.target.value ? parseInt(e.target.value) : undefined })
          }
        />
      </div>
      <div>
        <Label className="text-xs">TTL (seconds)</Label>
        <Input
          className="mt-1 h-8 text-xs"
          type="number"
          placeholder="3600"
          value={config.ttl_seconds || ""}
          onChange={(e) =>
            onUpdate({ ttl_seconds: e.target.value ? parseInt(e.target.value) : undefined })
          }
        />
      </div>
      {config.memory_type === "vector" && (
        <>
          <div>
            <Label className="text-xs">Embedding Model</Label>
            <Select
              value={config.embedding_model || "text-embedding-3-small"}
              onValueChange={(v) => onUpdate({ embedding_model: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text-embedding-3-small" className="text-xs">text-embedding-3-small</SelectItem>
                <SelectItem value="text-embedding-3-large" className="text-xs">text-embedding-3-large</SelectItem>
                <SelectItem value="text-embedding-ada-002" className="text-xs">text-embedding-ada-002</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Similarity Threshold</Label>
            <Input
              className="mt-1 h-8 text-xs"
              type="number"
              placeholder="0.7"
              step="0.05"
              min="0"
              max="1"
              value={config.similarity_threshold ?? ""}
              onChange={(e) =>
                onUpdate({
                  similarity_threshold: e.target.value ? parseFloat(e.target.value) : undefined,
                })
              }
            />
          </div>
        </>
      )}
    </div>
  );
}
