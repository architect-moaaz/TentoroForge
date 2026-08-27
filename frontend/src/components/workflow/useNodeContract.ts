import { useMemo } from "react";
import { asObjectList } from "./config-guards";
import type { InputMapping } from "./actionContracts";
import type { AppModel } from "@/types/app-model";
import type { WorkflowNodeConfig } from "@/types/workflow";
import {
  getContract,
  sqlTypeToParamType,
  type ActionContract,
  type ParamContract,
} from "./actionContracts";

/**
 * Resolves the runtime contract for a node given its current config +
 * the app model. The main job here is applying `expandFromTable`:
 * when the action targets a specific table, the panel needs one input
 * row per column (e.g. `values.email`, `values.name`, …). This hook
 * synthesizes those rows from `appModel.database.tables`.
 *
 * Returns null for nodes whose actionType has no declared contract yet —
 * callers should fall back to the legacy actionFieldSpecs renderer in
 * that case.
 */
export function useNodeContract(
  config: WorkflowNodeConfig,
  appModel: AppModel | null,
): ActionContract | null {
  return useMemo(() => {
    const base = getContract(config.actionType);
    if (!base) return null;
    if (!base.expandFromTable) return base;

    // Which table did the user pick? Try the input-mapping first (new
    // shape), then fall back to the legacy top-level config field so the
    // panel still expands correctly for unmigrated nodes.
    const tableInput = base.expandFromTable.tableInputName;
    // A3-2/A4-3: this is the THIRD reader of inputMappings and had the same
    // nullish-only guard as the other two. Found by the Area 11 fuzz sweep
    // after the first two were patched and it still crashed.
    const mapped = asObjectList<InputMapping>(config.inputMappings).find(
      (m) => m.name === tableInput,
    );
    const tableName =
      (mapped?.source === "literal" ? String(mapped.value ?? "") : "") ||
      (config as Record<string, unknown>)[tableInput] as string | undefined ||
      "";

    if (!tableName) return base;

    const table = appModel?.database?.tables?.find((t) => t.name === tableName);
    if (!table) return base;

    const into = base.expandFromTable.into;
    const mode = base.expandFromTable.mode;
    const synthesized: ParamContract[] = table.columns
      .filter((c) => (mode === "no-primary-key" ? !c.primaryKey : true))
      .map((c) => ({
        name: `${into}.${c.name}`,
        type: sqlTypeToParamType(c.type),
        required: !c.nullable && !c.default,
        label: c.name,
        source: `column:${table.name}.${c.name}`,
      }));

    // Drop the container input (the one we're expanding into is served
    // by the synthesized rows) and append the expanded rows.
    const withoutContainer = base.inputs.filter((i) => i.name !== into);
    return {
      ...base,
      inputs: [...withoutContainer, ...synthesized],
    };
  }, [config, appModel]);
}
