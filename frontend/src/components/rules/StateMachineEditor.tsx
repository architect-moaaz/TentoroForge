"use client";

import { useState, useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Plus, Trash2 } from "lucide-react";
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
import type { RuleConfig, StateTransition } from "@/types/rules";

interface StateMachineEditorProps {
  modelNames: string[];
  config: RuleConfig;
  modelName: string;
  fieldName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
  onFieldChange: (field: string) => void;
}

function statesToNodes(states: string[]): Node[] {
  return states.map((state, i) => ({
    id: state,
    data: { label: state },
    position: { x: 150 + (i % 3) * 200, y: 50 + Math.floor(i / 3) * 120 },
    style: {
      padding: "8px 16px",
      borderRadius: "8px",
      border: "2px solid #6366f1",
      background: "#eef2ff",
      fontSize: "12px",
      fontWeight: 600,
    },
  }));
}

function transitionsToEdges(transitions: StateTransition[]): Edge[] {
  return transitions.map((t, i) => ({
    id: `${t.from}-${t.to}-${i}`,
    source: t.from,
    target: t.to,
    label: t.label || t.condition || "",
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { strokeWidth: 2 },
    labelStyle: { fontSize: 10 },
  }));
}

export function StateMachineEditor({
  modelNames,
  config,
  modelName,
  fieldName,
  onConfigChange,
  onModelChange,
  onFieldChange,
}: StateMachineEditorProps) {
  const states = config.states || [];
  const transitions = config.transitions || [];

  const [newState, setNewState] = useState("");
  const [newTransFrom, setNewTransFrom] = useState("");
  const [newTransTo, setNewTransTo] = useState("");
  const [newTransLabel, setNewTransLabel] = useState("");

  const initialNodes = useMemo(() => statesToNodes(states), [states]);
  const initialEdges = useMemo(() => transitionsToEdges(transitions), [transitions]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) => addEdge({ ...params, animated: true, markerEnd: { type: MarkerType.ArrowClosed } }, eds));
      if (params.source && params.target) {
        const newTransitions = [
          ...transitions,
          { from: params.source, to: params.target, label: "", condition: "" },
        ];
        onConfigChange({ ...config, transitions: newTransitions });
      }
    },
    [setEdges, transitions, config, onConfigChange],
  );

  const addState = () => {
    const name = newState.trim();
    if (!name || states.includes(name)) return;
    onConfigChange({ ...config, states: [...states, name] });
    setNewState("");
  };

  const removeState = (state: string) => {
    onConfigChange({
      ...config,
      states: states.filter((s) => s !== state),
      transitions: transitions.filter(
        (t) => t.from !== state && t.to !== state,
      ),
    });
  };

  const addTransition = () => {
    if (!newTransFrom || !newTransTo) return;
    onConfigChange({
      ...config,
      transitions: [
        ...transitions,
        { from: newTransFrom, to: newTransTo, label: newTransLabel, condition: "" },
      ],
    });
    setNewTransLabel("");
  };

  const removeTransition = (index: number) => {
    onConfigChange({
      ...config,
      transitions: transitions.filter((_, i) => i !== index),
    });
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Model</Label>
          <Select value={modelName} onValueChange={onModelChange}>
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select model..." />
            </SelectTrigger>
            <SelectContent>
              {modelNames.map((m) => (
                <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">State Field</Label>
          <Input
            className="mt-1 h-8 text-xs"
            placeholder="e.g. status"
            value={fieldName || config.stateField || "status"}
            onChange={(e) => {
              onFieldChange(e.target.value);
              onConfigChange({ ...config, stateField: e.target.value });
            }}
          />
        </div>
      </div>

      {/* States list */}
      <div>
        <Label className="text-xs">States</Label>
        <div className="mt-1 flex flex-wrap gap-1">
          {states.map((s) => (
            <span
              key={s}
              className="inline-flex items-center gap-1 rounded-full border bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700"
            >
              {s}
              <button
                type="button"
                className="hover:text-red-500"
                onClick={() => removeState(s)}
              >
                <Trash2 className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
        </div>
        <div className="mt-1 flex gap-2">
          <Input
            className="h-7 flex-1 text-xs"
            placeholder="New state name..."
            value={newState}
            onChange={(e) => setNewState(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addState()}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={addState}
          >
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Transitions list */}
      <div>
        <Label className="text-xs">Transitions</Label>
        <div className="mt-1 space-y-1">
          {transitions.map((t, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="font-medium">{t.from}</span>
              <span className="text-muted-foreground">→</span>
              <span className="font-medium">{t.to}</span>
              {t.label && (
                <span className="text-muted-foreground">({t.label})</span>
              )}
              <button
                type="button"
                className="ml-auto text-muted-foreground hover:text-red-500"
                onClick={() => removeTransition(i)}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
        {states.length >= 2 && (
          <div className="mt-1 flex gap-2">
            <Select value={newTransFrom} onValueChange={setNewTransFrom}>
              <SelectTrigger className="h-7 w-[100px] text-xs">
                <SelectValue placeholder="From..." />
              </SelectTrigger>
              <SelectContent>
                {states.map((s) => (
                  <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="self-center text-xs text-muted-foreground">→</span>
            <Select value={newTransTo} onValueChange={setNewTransTo}>
              <SelectTrigger className="h-7 w-[100px] text-xs">
                <SelectValue placeholder="To..." />
              </SelectTrigger>
              <SelectContent>
                {states.map((s) => (
                  <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              className="h-7 flex-1 text-xs"
              placeholder="Label..."
              value={newTransLabel}
              onChange={(e) => setNewTransLabel(e.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={addTransition}
            >
              <Plus className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>

      {/* Visual diagram */}
      {states.length > 0 && (
        <div className="h-[250px] rounded-md border bg-white">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      )}
    </div>
  );
}
