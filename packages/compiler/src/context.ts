/**
 * EmitContext — carries state through the recursive node emission process.
 *
 * Tracks imports, hooks, state declarations, and handlers that each emitter
 * contributes to, which are assembled into the final file at the end.
 */

export interface ImportSpec {
  from: string;
  named?: string[];
  default?: string;
}

export interface StateDeclaration {
  name: string;
  type: string;
  initialValue: string;
}

export class EmitContext {
  indent: number = 0;
  scope: "page" | "component" = "page";
  /** Current iterator variable: "item" inside Repeater, "row.original" inside DataTable column */
  iteratorVar: string | null = null;
  /** Declared page state fields */
  pageStateKeys: Set<string> = new Set();
  /** Declared data source names */
  dataSourceNames: Set<string> = new Set();

  // Collected output sections
  private _imports: Map<string, Set<string>> = new Map();
  private _defaultImports: Map<string, string> = new Map();
  private _hookCalls: string[] = [];
  private _stateDeclarations: StateDeclaration[] = [];
  private _handlers: string[] = [];
  private _helpers: string[] = [];
  private _fileHeaders: string[] = [];
  private _effects: string[] = [];

  /** Track whether "use client" is needed */
  needsClientDirective: boolean = false;

  /** The current node path (for data-ir-path attributes in dev mode) */
  currentPath: number[] = [];
  devMode: boolean = false;

  constructor(init?: Partial<EmitContext>) {
    if (init) Object.assign(this, init);
  }

  /** Clone context for a child scope (new indent, iterator, etc.) */
  child(overrides?: Partial<EmitContext>): EmitContext {
    const child = new EmitContext();
    child.indent = this.indent + 1;
    child.scope = this.scope;
    child.iteratorVar = this.iteratorVar;
    child.pageStateKeys = this.pageStateKeys;
    child.dataSourceNames = this.dataSourceNames;
    child._imports = this._imports;
    child._defaultImports = this._defaultImports;
    child._hookCalls = this._hookCalls;
    child._stateDeclarations = this._stateDeclarations;
    child._handlers = this._handlers;
    child._helpers = this._helpers;
    child._fileHeaders = this._fileHeaders;
    child._effects = this._effects;
    child.needsClientDirective = this.needsClientDirective;
    child.currentPath = [...this.currentPath];
    child.devMode = this.devMode;
    if (overrides) Object.assign(child, overrides);
    return child;
  }

  // ── Imports ──

  ensureImport(from: string, ...named: string[]): void {
    if (!this._imports.has(from)) {
      this._imports.set(from, new Set());
    }
    for (const n of named) {
      this._imports.get(from)!.add(n);
    }
  }

  ensureDefaultImport(from: string, name: string): void {
    this._defaultImports.set(from, name);
  }

  getImports(): ImportSpec[] {
    const result: ImportSpec[] = [];
    // Default imports
    for (const [from, name] of this._defaultImports) {
      result.push({ from, default: name });
    }
    // Named imports
    for (const [from, names] of this._imports) {
      if (names.size > 0) {
        result.push({ from, named: [...names].sort() });
      }
    }
    return result;
  }

  // ── Hooks ──

  addHookCall(code: string): void {
    if (!this._hookCalls.includes(code)) {
      this._hookCalls.push(code);
      this.needsClientDirective = true;
    }
  }

  getHookCalls(): string[] {
    return this._hookCalls;
  }

  // ── State ──

  addState(name: string, type: string, initialValue: string): void {
    if (this._stateDeclarations.some((s) => s.name === name)) return;
    this._stateDeclarations.push({ name, type, initialValue });
    this.needsClientDirective = true;
  }

  getStateDeclarations(): StateDeclaration[] {
    return this._stateDeclarations;
  }

  // ── Handlers ──

  addHandler(code: string): void {
    this._handlers.push(code);
  }

  getHandlers(): string[] {
    return this._handlers;
  }

  // ── Helpers ──

  addHelper(code: string): void {
    if (!this._helpers.includes(code)) {
      this._helpers.push(code);
    }
  }

  getHelpers(): string[] {
    return this._helpers;
  }

  // ── File headers (Zod schemas, type defs, etc.) ──

  addFileHeader(code: string): void {
    this._fileHeaders.push(code);
  }

  getFileHeaders(): string[] {
    return this._fileHeaders;
  }

  // ── Effects ──

  addEffect(code: string): void {
    if (!this._effects.includes(code)) {
      this._effects.push(code);
      this.needsClientDirective = true;
    }
  }

  getEffects(): string[] {
    return this._effects;
  }
}

// ── Indentation helper ──

export function indent(code: string, level: number): string {
  const prefix = "  ".repeat(level);
  return code
    .split("\n")
    .map((line) => (line.trim() ? prefix + line : ""))
    .join("\n");
}
