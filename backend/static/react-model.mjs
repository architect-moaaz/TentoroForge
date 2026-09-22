#!/usr/bin/env node
/**
 * The React source adapter of the visual editor.
 *
 * A coded page is two files the UI engineer wrote — `view.tsx` and `load.ts`.
 * The editor never treats the rendered DOM as the page: it reads the JSX with
 * a real parser, gives every element a stable structural id, and edits the
 * source by splicing at parser-reported spans. Formatting, hooks, handlers
 * and everything outside the touched span are left exactly as they were.
 *
 * Commands (JSON on stdin, JSON on stdout):
 *
 *   model     {view, load?}            → {ok, roots, nodes, imports, loadKeys, viewProps}
 *   patch     {view, ops: [...]}       → {ok, view, applied} | {ok: false, error}
 *   patchLoad {load, ops: [...]}       → {ok, load, applied}   addReturnKey / removeReturnKey / addImport
 *   annotate  {view}                   → {ok, view}   every JSX opening element gets data-fid="<id>"
 *
 * Ids are paths: `r0` is the first JSX root of the file (normally the View's
 * return), `r0.2.1` its third child's second child. A child reached through an
 * expression container (`{cond && <X/>}`, `{rows.map(r => <Row/>)}`) is still a
 * child, with `context` saying "conditional" or "repeat" so the editor can
 * protect what it must not restructure.
 */
import { parse } from "@babel/parser";
import { sampleRow } from "./jit-samples.mjs";

// ---------------------------------------------------------------------------
// Parsing and the model
// ---------------------------------------------------------------------------

function parseTsx(source) {
  return parse(source, {
    sourceType: "module",
    plugins: ["typescript", "jsx"],
    errorRecovery: false,
  });
}

function isNode(v) {
  return v && typeof v === "object" && typeof v.type === "string";
}

function children(node) {
  const out = [];
  for (const key of Object.keys(node)) {
    if (key === "loc" || key === "leadingComments" || key === "trailingComments" || key === "innerComments") continue;
    const v = node[key];
    if (Array.isArray(v)) {
      for (const x of v) if (isNode(x)) out.push(x);
    } else if (isNode(v)) out.push(v);
  }
  return out;
}

const REPEAT_CALLS = new Set(["map", "flatMap"]);

function elementName(node) {
  const n = node.type === "JSXElement" ? node.openingElement.name : null;
  if (!n) return "Fragment";
  if (n.type === "JSXIdentifier") return n.name;
  if (n.type === "JSXNamespacedName") return `${n.namespace.name}:${n.name.name}`;
  if (n.type === "JSXMemberExpression") {
    const parts = [];
    let cur = n;
    while (cur.type === "JSXMemberExpression") { parts.unshift(cur.property.name); cur = cur.object; }
    parts.unshift(cur.name);
    return parts.join(".");
  }
  return "unknown";
}

function attrValue(source, attr) {
  const v = attr.value;
  if (v == null) return { kind: "true", value: null, valueSpan: null };
  if (v.type === "StringLiteral") return { kind: "string", value: v.value, valueSpan: [v.start, v.end] };
  if (v.type === "JSXExpressionContainer") {
    const e = v.expression;
    if (e.type === "StringLiteral") return { kind: "string", value: e.value, valueSpan: [v.start, v.end] };
    if (e.type === "TemplateLiteral" && e.expressions.length === 0)
      return { kind: "string", value: e.quasis.map((q) => q.value.cooked ?? "").join(""), valueSpan: [v.start, v.end] };
    if (e.type === "JSXElement" || e.type === "JSXFragment")
      return { kind: "jsx", value: source.slice(e.start, e.end), valueSpan: [v.start, v.end] };
    if (e.type === "BooleanLiteral") return { kind: "expr", value: String(e.value), valueSpan: [v.start, v.end] };
    if (e.type === "NumericLiteral") return { kind: "expr", value: String(e.value), valueSpan: [v.start, v.end] };
    return { kind: "expr", value: source.slice(e.start, e.end), valueSpan: [v.start, v.end] };
  }
  if (v.type === "JSXElement" || v.type === "JSXFragment")
    return { kind: "jsx", value: source.slice(v.start, v.end), valueSpan: [v.start, v.end] };
  return { kind: "expr", value: source.slice(v.start, v.end), valueSpan: [v.start, v.end] };
}

function attrName(attr) {
  const n = attr.name;
  return n.type === "JSXNamespacedName" ? `${n.namespace.name}:${n.name.name}` : n.name;
}

/** Walk one JSX element's children, collecting the JSX elements that are its
 *  children in the editor's sense — directly, or through expression containers. */
function jsxChildrenOf(node) {
  const out = [];
  const kids = node.type === "JSXElement" ? node.children : node.children;
  for (const c of kids) collectFrom(c, null, null, out);
  return out;
}

// Descend a non-JSX expression looking for JSX, remembering the container it
// sat in and the context (repeat / conditional) it came through.
let SRC = "";
function collectFrom(node, container, context, out, repeat = null) {
  if (node.type === "JSXElement" || node.type === "JSXFragment") {
    out.push({ node, container, context, repeat });
    return;
  }
  if (node.type === "JSXText" || node.type === "JSXEmptyExpression") return;
  if (node.type === "JSXExpressionContainer") {
    collectFrom(node.expression, node, context, out, repeat);
    return;
  }
  if (node.type === "JSXSpreadChild") return;
  if (node.type === "CallExpression" && node.callee.type === "MemberExpression"
      && node.callee.property.type === "Identifier" && REPEAT_CALLS.has(node.callee.property.name)) {
    // `source.map((row) => …)`: what is repeated, and what each row is called.
    const fn = node.arguments[0];
    const param = fn && fn.params && fn.params[0];
    const repeat = { source: SRC.slice(node.callee.object.start, node.callee.object.end),
                     variable: param && param.type === "Identifier" ? param.name : null };
    for (const arg of node.arguments) collectFrom(arg, container, "repeat", out, repeat);
    return;
  }
  if (node.type === "LogicalExpression" && node.operator === "&&") {
    // `{cond && <X/>}`: X is shown when cond holds.
    const cond = SRC.slice(node.left.start, node.left.end);
    const before = out.length;
    collectFrom(node.right, container, context ?? "conditional", out, repeat);
    for (let i = before; i < out.length; i++) if (!out[i].condition) out[i].condition = cond;
    return;
  }
  if (node.type === "LogicalExpression" || node.type === "ConditionalExpression") {
    for (const c of children(node)) collectFrom(c, container, context ?? "conditional", out, repeat);
    return;
  }
  if (node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression") {
    collectFrom(node.body, container, context, out, repeat);
    return;
  }
  if (node.type === "BlockStatement") {
    for (const s of node.body) if (s.type === "ReturnStatement" && s.argument) collectFrom(s.argument, container, context, out, repeat);
    return;
  }
  if (node.type === "ParenthesizedExpression" || node.type === "TSAsExpression" || node.type === "TSNonNullExpression") {
    collectFrom(node.expression, container, context, out, repeat);
    return;
  }
  // Anything else (a plain `{row.name}`, a call) holds no editable JSX child.
}

function lineIndent(source, pos) {
  const lineStart = source.lastIndexOf("\n", pos - 1) + 1;
  const m = /^[ \t]*/.exec(source.slice(lineStart, pos));
  return m ? m[0] : "";
}

function directText(source, node) {
  // The element's own text: JSXText and string-literal containers, in order.
  // `mixed` when a non-literal expression sits among the text.
  let text = "";
  let mixed = false;
  let hasElementChild = false;
  for (const c of node.children) {
    if (c.type === "JSXText") text += c.value;
    else if (c.type === "JSXExpressionContainer") {
      const e = c.expression;
      if (e.type === "StringLiteral") text += e.value;
      else if (e.type === "JSXEmptyExpression") continue;
      else { mixed = true; text += source.slice(c.start, c.end); }
    } else if (c.type === "JSXElement" || c.type === "JSXFragment") hasElementChild = true;
  }
  const collapsed = text.replace(/\s*\n\s*/g, " ").trim();
  return { text: collapsed, mixed, hasElementChild };
}

function buildNode(source, entry, id, parentId, nodes, index) {
  const { node, container, context, repeat, condition } = entry;
  const isFragment = node.type === "JSXFragment";
  const opening = isFragment ? node.openingFragment : node.openingElement;
  const closing = isFragment ? node.closingFragment : node.closingElement;
  const name = isFragment ? "Fragment" : elementName(node);
  const kind = isFragment ? "fragment" : /^[a-z]/.test(name) ? "element" : "component";
  const props = isFragment ? [] : opening.attributes.map((a) => {
    if (a.type === "JSXSpreadAttribute")
      return { name: `...${source.slice(a.argument.start, a.argument.end)}`, kind: "spread", value: null, span: [a.start, a.end], valueSpan: null };
    const v = attrValue(source, a);
    return { name: attrName(a), ...v, span: [a.start, a.end] };
  });
  SRC = source;
  const kids = jsxChildrenOf(node);
  const own = directText(source, node);
  const meaningful = node.children.filter((c) => !(c.type === "JSXText" && !c.value.trim()));
  const only = meaningful.length === 1 && meaningful[0].type === "JSXExpressionContainer" && meaningful[0].expression.type !== "JSXEmptyExpression" ? meaningful[0] : null;
  const exprOnly = only ? source.slice(only.expression.start, only.expression.end) : null;
  const objects = {};
  if (!isFragment) {
    for (const a of opening.attributes) {
      if (a.type !== "JSXAttribute" || !a.value || a.value.type !== "JSXExpressionContainer") continue;
      if (a.value.expression.type === "ObjectExpression") objects[attrName(a)] = objectEntries(source, a.value.expression);
    }
  }
  // A child reached through an expression (`{rows.map(...)}`) is a child, not text.
  const hasElementChild = own.hasElementChild || kids.length > 0;
  const { text, mixed } = own;
  const rec = {
    id,
    parent: parentId,
    index,
    type: name,
    kind,
    props,
    text: hasElementChild ? null : text,
    textEditable: !hasElementChild && !mixed,
    inner: closing ? source.slice(opening.end, closing.start) : null,
    innerSpan: closing ? [opening.end, closing.start] : null,
    selfClosing: !closing,
    span: [node.start, node.end],
    wrapperSpan: container ? [container.start, container.end] : null,
    line: node.loc.start.line,
    endLine: node.loc.end.line,
    context: context ?? null,
    repeat: repeat ?? null,
    condition: condition ?? null,
    exprOnly,
    objects,
    children: [],
  };
  nodes[id] = rec;
  kids.forEach((k, i) => {
    const cid = `${id}.${i}`;
    rec.children.push(cid);
    buildNode(source, k, cid, id, nodes, i);
  });
  return rec;
}

/** Top-level JSX in the file: the return of each function, in source order. */
function jsxRoots(ast) {
  const roots = [];
  const visit = (node, owner) => {
    if (node.type === "JSXElement" || node.type === "JSXFragment") {
      roots.push({ node, owner });
      return; // nested JSX is reached through the element's own children
    }
    let nextOwner = owner;
    if (node.type === "FunctionDeclaration" && node.id) nextOwner = node.id.name;
    if (node.type === "VariableDeclarator" && node.id.type === "Identifier"
        && node.init && (node.init.type === "ArrowFunctionExpression" || node.init.type === "FunctionExpression"))
      nextOwner = node.id.name;
    if (node.type === "ExportDefaultDeclaration" && node.declaration.type === "FunctionDeclaration" && !node.declaration.id)
      nextOwner = "View";
    for (const c of children(node)) visit(c, nextOwner);
  };
  visit(ast.program, null);
  return roots;
}

function importsOf(source, ast) {
  const out = [];
  for (const s of ast.program.body) {
    if (s.type !== "ImportDeclaration") continue;
    out.push({
      source: s.source.value,
      names: s.specifiers.map((sp) => sp.type === "ImportDefaultSpecifier" ? `default:${sp.local.name}`
        : sp.type === "ImportNamespaceSpecifier" ? `*:${sp.local.name}` : sp.local.name),
      span: [s.start, s.end],
      typeOnly: s.importKind === "type",
    });
  }
  return out;
}

function viewParam(ast) {
  // How the View takes its data: `(props: Props)`, `({ a, b }: Props)`, or nothing.
  for (const s of ast.program.body) {
    if (s.type !== "ExportDefaultDeclaration") continue;
    const fn = s.declaration;
    if (!fn || !fn.params) return null;
    if (!fn.params.length) return { kind: "none", span: [fn.start, fn.end] };
    const p = fn.params[0];
    if (p.type === "ObjectPattern") return { kind: "pattern", names: p.properties.filter((x) => x.type === "ObjectProperty").map((x) => x.key.name ?? x.key.value), span: [p.start, p.end] };
    if (p.type === "Identifier") return { kind: "identifier", name: p.name };
  }
  return null;
}

function viewProps(ast) {
  // `export default function View({ a, b }: Props)` → ["a", "b"]; `(props)` → ["props"].
  for (const s of ast.program.body) {
    if (s.type !== "ExportDefaultDeclaration") continue;
    const fn = s.declaration;
    if (!fn || !fn.params || !fn.params.length) return [];
    const p = fn.params[0];
    if (p.type === "ObjectPattern") return p.properties.filter((x) => x.type === "ObjectProperty").map((x) => x.key.name ?? x.key.value);
    if (p.type === "Identifier") return [p.name];
  }
  return [];
}

function loadKeys(load) {
  // What `load()` returns: the keys of its top-level `return { ... }`.
  if (!load) return [];
  let ast;
  try { ast = parseTsx(load); } catch { return []; }
  let fn = null;
  for (const s of ast.program.body) {
    const d = s.type === "ExportNamedDeclaration" ? s.declaration : s;
    if (d && d.type === "FunctionDeclaration" && d.id && d.id.name === "load") fn = d;
  }
  if (!fn) return [];
  const keys = new Set();
  const walk = (n) => {
    if (n.type === "ReturnStatement" && n.argument && n.argument.type === "ObjectExpression") {
      for (const p of n.argument.properties) {
        if (p.type === "ObjectProperty") keys.add(p.key.name ?? p.key.value);
        else if (p.type === "SpreadElement") keys.add(`...${load.slice(p.argument.start, p.argument.end)}`);
      }
      return;
    }
    if (n.type === "ArrowFunctionExpression" || n.type === "FunctionExpression" || n.type === "FunctionDeclaration") {
      if (n !== fn) return; // a return inside a nested callback is not the page's
    }
    for (const c of children(n)) walk(c);
  };
  walk(fn.body);
  return [...keys];
}

/** An object literal prop (`fields={{ … }}`, `input={{ … }}`) as entries the editor can show and rewrite. */
function objectEntries(source, obj) {
  const out = [];
  for (const p of obj.properties) {
    if (p.type === "SpreadElement") { out.push({ key: `...${source.slice(p.argument.start, p.argument.end)}`, code: source.slice(p.start, p.end), kind: "spread" }); continue; }
    if (p.type !== "ObjectProperty") { out.push({ key: source.slice(p.key ? p.key.start : p.start, p.key ? p.key.end : p.end), code: source.slice(p.start, p.end), kind: "method" }); continue; }
    const key = p.key.type === "Identifier" ? p.key.name : p.key.type === "StringLiteral" ? p.key.value : source.slice(p.key.start, p.key.end);
    const v = p.value;
    const entry = { key, code: source.slice(v.start, v.end), kind: "expr" };
    if (v.type === "StringLiteral") { entry.kind = "string"; entry.value = v.value; }
    else if (v.type === "NumericLiteral") { entry.kind = "number"; entry.value = v.value; }
    else if (v.type === "BooleanLiteral") { entry.kind = "boolean"; entry.value = v.value; }
    else if (v.type === "ObjectExpression") { entry.kind = "object"; entry.entries = objectEntries(source, v); }
    else if (v.type === "ArrayExpression" && v.elements.every((e) => e && e.type === "ObjectExpression")) { entry.kind = "objects"; entry.items = v.elements.map((e) => objectEntries(source, e)); }
    else if (v.type === "ArrayExpression" && v.elements.every((e) => e && e.type === "StringLiteral")) { entry.kind = "strings"; entry.value = v.elements.map((e) => e.value); }
    out.push(entry);
  }
  return out;
}

//: The server SDK's reads and what each returns, for `loadShapes`. Each
//: shape also says HOW the value is obtained (`via`): read on the server
//: from the database (the SDK's reads), computed by a widget's query, the
//: signed-in person, the page's address, fetched from an API, or written in.
const READS = {
  list: (a, raw, nodes) => ({ kind: "rows", entity: a[0], via: { how: "server", call: "list", entity: a[0] }, ...readOptionsOf(nodes[1]) }),
  listPage: (a, raw, nodes) => ({ kind: "page", entity: a[0], via: { how: "server", call: "listPage", entity: a[0] }, ...readOptionsOf(nodes[1]) }),
  record: (a) => ({ kind: "record", entity: a[0], via: { how: "server", call: "record", entity: a[0] } }),
  count: (a) => ({ kind: "number", via: { how: "server", call: "count", entity: a[0] } }),
  total: (a) => ({ kind: "number", via: { how: "server", call: "total", entity: a[0] } }),
  series: (a) => ({ kind: "series", via: { how: "server", call: "series", entity: a[0] } }),
  query: (a) => ({ kind: "query", entity: a[0], via: { how: "server", call: "query", entity: a[0] } }),
  runWidget: (a, raw) => { const w = (/^widgets\.(\w+)/.exec(raw[0] || "") || [])[1] || null; return { kind: "widget", widget: w, via: { how: "widget", widget: w } }; },
  currentUser: () => ({ kind: "user", via: { how: "user" } }),
};

/** A literal's value — string, number, boolean, null, an array or object of
 *  literals — or `undefined` when code decides it. */
function literalValue(node) {
  if (!node) return undefined;
  switch (node.type) {
    case "StringLiteral": return node.value;
    case "NumericLiteral": return node.value;
    case "BooleanLiteral": return node.value;
    case "NullLiteral": return null;
    case "TemplateLiteral": return node.expressions.length ? undefined : node.quasis.map((q) => q.value.cooked).join("");
    case "UnaryExpression": { const v = literalValue(node.argument); return node.operator === "-" && typeof v === "number" ? -v : undefined; }
    case "ArrayExpression": { const out = []; for (const e of node.elements) { const v = literalValue(e); if (v === undefined) return undefined; out.push(v); } return out; }
    case "ObjectExpression": {
      const out = {};
      for (const p of node.properties) {
        if (p.type !== "ObjectProperty" || p.computed) return undefined;
        const v = literalValue(p.value);
        if (v === undefined) return undefined;
        out[p.key.name ?? p.key.value] = v;
      }
      return out;
    }
    case "TSAsExpression": case "ParenthesizedExpression": return literalValue(node.expression);
    default: return undefined;
  }
}

/** A read's options (`list("X", { where, sort, order, limit })`) as data,
 *  or a note that code decides them. */
function readOptionsOf(node) {
  if (!node) return { options: {} };
  const v = literalValue(node);
  return v && typeof v === "object" && !Array.isArray(v) ? { options: v } : { optionsCustom: true };
}

/** The literal text for a read's options; null when there are none. */
function optionsLiteral(o) {
  const parts = [];
  const key = (k) => (/^[A-Za-z_$][\w$]*$/.test(k) ? k : JSON.stringify(k));
  if (o.where && Object.keys(o.where).length) parts.push(`where: { ${Object.entries(o.where).map(([k, v]) => `${key(k)}: ${JSON.stringify(v)}`).join(", ")} }`);
  if (o.search) parts.push(`search: ${JSON.stringify(String(o.search))}`);
  if (o.sort) parts.push(`sort: ${JSON.stringify(String(o.sort))}`);
  if (o.order) parts.push(`order: ${JSON.stringify(String(o.order))}`);
  if (o.limit) parts.push(`limit: ${Number(o.limit)}`);
  if (o.page) parts.push(`page: ${Number(o.page)}`);
  return parts.length ? `{ ${parts.join(", ")} }` : null;
}

/** The SDK read call whose result `load` returns under `key`, or null. */
function readCallFor(ast, key) {
  const m = loadModelFromAst(ast);
  if (!m.fn) return null;
  const unwrap = (e) => { while (e && (e.type === "AwaitExpression" || e.type === "ParenthesizedExpression" || e.type === "TSAsExpression" || e.type === "TSNonNullExpression")) e = e.argument ?? e.expression; return e; };
  const isRead = (e) => e && e.type === "CallExpression" && e.callee.type === "Identifier" && READS[e.callee.name];
  const vars = new Map();
  const walk = (n) => {
    if (n.type === "VariableDeclarator" && n.init) {
      const init = unwrap(n.init);
      if (n.id.type === "Identifier") vars.set(n.id.name, init);
      else if (n.id.type === "ArrayPattern" && init && init.type === "CallExpression" && init.arguments[0] && init.arguments[0].type === "ArrayExpression") {
        n.id.elements.forEach((el, i) => { if (el && el.type === "Identifier") vars.set(el.name, unwrap(init.arguments[0].elements[i])); });
      }
    }
    if ((n.type === "ArrowFunctionExpression" || n.type === "FunctionExpression" || n.type === "FunctionDeclaration") && n !== m.fn) return;
    for (const c of children(n)) walk(c);
  };
  walk(m.fn.body);
  for (const { obj } of m.returns) {
    for (const p of obj.properties) {
      if (p.type !== "ObjectProperty" || (p.key.name ?? p.key.value) !== key) continue;
      let v = unwrap(p.value);
      if (v.type === "Identifier") v = vars.get(v.name);
      if (v && v.type === "MemberExpression" && v.object.type === "Identifier") v = vars.get(v.object.name);
      if (isRead(v)) return v;
    }
  }
  return null;
}

function opSetReadOptions(source, m, op) {
  needLoad(m);
  const call = readCallFor(parseTsx(source), op.key);
  if (!call) throw new PatchError("no-read", "This list is not read in a way the editor can change — ask Smith.");
  if (call.arguments[1] && readOptionsOf(call.arguments[1]).optionsCustom) {
    throw new PatchError("custom-options", "How this list is read is decided by code on this page — ask Smith to change it.");
  }
  const lit = optionsLiteral(op.options || {});
  const args = call.arguments;
  if (args.length >= 2) return lit ? splice(source, args[1].start, args[1].end, lit) : splice(source, args[0].end, args[1].end, "");
  return lit ? splice(source, args[0].end, args[0].end, `, ${lit}`) : source;
}

/** The `fetch(…)` call an expression is built on, if any: `fetch(u)`,
 *  `(await fetch(u)).json()`, `fetch(u).then(…)`. */
function fetchCallOf(expr) {
  let e = expr;
  for (let i = 0; e && i < 6; i++) {
    if (e.type === "AwaitExpression" || e.type === "ParenthesizedExpression" || e.type === "TSAsExpression") { e = e.argument ?? e.expression; continue; }
    if (e.type === "CallExpression" && e.callee.type === "Identifier" && e.callee.name === "fetch") return e;
    if (e.type === "CallExpression" && e.callee.type === "MemberExpression") { e = e.callee.object; continue; }
    if (e.type === "MemberExpression") { e = e.object; continue; }
    return null;
  }
  return null;
}

function shapeOf(expr, vars, source) {
  // Unwrap `await`, parentheses, `as`, `!`.
  while (expr && (expr.type === "AwaitExpression" || expr.type === "ParenthesizedExpression" || expr.type === "TSAsExpression" || expr.type === "TSNonNullExpression")) expr = expr.argument ?? expr.expression;
  if (!expr) return { kind: "unknown" };
  if (expr.type === "CallExpression" && expr.callee.type === "Identifier" && READS[expr.callee.name]) {
    const args = expr.arguments.map((a) => (a.type === "StringLiteral" ? a.value : null));
    const raw = expr.arguments.map((a) => source.slice(a.start, a.end));
    return READS[expr.callee.name](args, raw, expr.arguments);
  }
  // fetch(url) — or (await fetch(url)).json(): fetched from an API.
  const fetched = fetchCallOf(expr);
  if (fetched) {
    const u = fetched.arguments[0];
    return { kind: "unknown", via: { how: "api", url: u ? source.slice(u.start, u.end).replace(/^["'`]|["'`]$/g, "") : "" } };
  }
  if (expr.type === "Identifier") return vars.get(expr.name) ?? { kind: "unknown" };
  if (expr.type === "MemberExpression" && expr.object.type === "Identifier" && expr.property.type === "Identifier") {
    const base = vars.get(expr.object.name);
    if (base && base.kind === "page") return expr.property.name === "rows" ? { kind: "rows", entity: base.entity, via: base.via } : expr.property.name === "total" ? { kind: "number", via: base.via } : { kind: "unknown", via: base.via };
    if (base && base.kind === "widget") return expr.property.name === "value" ? { kind: "number", via: base.via } : { kind: "unknown", via: base.via };
    if (expr.object.name === "ctx" || (base && base.kind === "context")) return { kind: "string", via: { how: "address" } };
  }
  // ctx.params.id, ctx.searchParams.q: from the page's address.
  if (expr.type === "MemberExpression" && expr.object.type === "MemberExpression" && expr.object.object.type === "Identifier"
      && (expr.object.object.name === "ctx" || (vars.get(expr.object.object.name) || {}).kind === "context")) return { kind: "string", via: { how: "address" } };
  if (expr.type === "StringLiteral" || expr.type === "TemplateLiteral") return { kind: "string", via: { how: "fixed" } };
  if (expr.type === "NumericLiteral") return { kind: "number", via: { how: "fixed" } };
  if (expr.type === "BooleanLiteral") return { kind: "boolean", via: { how: "fixed" } };
  if (expr.type === "LogicalExpression" || expr.type === "ConditionalExpression") {
    const a = shapeOf(expr.left ?? expr.consequent, vars, source);
    return a.kind === "unknown" ? shapeOf(expr.right ?? expr.alternate, vars, source) : a;
  }
  if (expr.type === "ArrayExpression") return { kind: "list" };
  return { kind: "unknown" };
}

/** What each key `load()` returns holds: rows of an entity, one record, a number… */
function loadShapes(load) {
  if (!load) return {};
  let ast;
  try { ast = parseTsx(load); } catch { return {}; }
  const m = loadModelFromAst(ast);
  if (!m.fn) return {};
  const vars = new Map();
  const walk = (n) => {
    if (n.type === "VariableDeclarator" && n.init) {
      if (n.id.type === "Identifier") vars.set(n.id.name, shapeOf(n.init, vars, load));
      else if (n.id.type === "ArrayPattern") {
        // const [a, b] = await Promise.all([list(…), count(…)])
        let init = n.init;
        while (init && (init.type === "AwaitExpression" || init.type === "ParenthesizedExpression")) init = init.argument ?? init.expression;
        const arr = init && init.type === "CallExpression" && init.arguments[0] && init.arguments[0].type === "ArrayExpression" ? init.arguments[0] : null;
        n.id.elements.forEach((el, i) => { if (el && el.type === "Identifier") vars.set(el.name, arr && arr.elements[i] ? shapeOf(arr.elements[i], vars, load) : { kind: "unknown" }); });
      } else if (n.id.type === "ObjectPattern") {
        const base = shapeOf(n.init, vars, load);
        for (const p of n.id.properties) if (p.type === "ObjectProperty" && p.value.type === "Identifier") vars.set(p.value.name, base.kind === "page" && p.key.name === "rows" ? { kind: "rows", entity: base.entity } : base.kind === "page" && p.key.name === "total" ? { kind: "number" } : { kind: "unknown" });
      }
    }
    if ((n.type === "ArrowFunctionExpression" || n.type === "FunctionExpression" || n.type === "FunctionDeclaration") && n !== m.fn) return;
    for (const c of children(n)) walk(c);
  };
  for (const p of m.fn.params || []) if (p.type === "Identifier") vars.set(p.name, { kind: "context" });
  walk(m.fn.body);
  const shapes = {};
  for (const { obj } of m.returns) {
    for (const p of obj.properties) {
      if (p.type !== "ObjectProperty") continue;
      const key = p.key.name ?? p.key.value;
      const shape = p.shorthand || (p.value.type === "Identifier") ? (vars.get(p.value.name) ?? shapeOf(p.value, vars, load)) : shapeOf(p.value, vars, load);
      if (!shapes[key] || shapes[key].kind === "unknown") shapes[key] = shape;
    }
  }
  return shapes;
}

function loadModelFromAst(ast) {
  let fn = null;
  for (const s of ast.program.body) {
    const d = s.type === "ExportNamedDeclaration" ? s.declaration : s;
    if (d && d.type === "FunctionDeclaration" && d.id && d.id.name === "load") fn = d;
    if (d && d.type === "VariableDeclaration") for (const v of d.declarations) if (v.id.type === "Identifier" && v.id.name === "load" && v.init && /Function/.test(v.init.type)) fn = v.init;
  }
  const returns = [];
  if (fn) {
    // A return inside a `catch` is the page's fallback shape, not its data.
    const walk = (n, inCatch) => {
      if (n.type === "ReturnStatement" && n.argument) {
        let arg = n.argument;
        while (arg.type === "TSAsExpression" || arg.type === "ParenthesizedExpression" || arg.type === "TSSatisfiesExpression") arg = arg.expression;
        if (arg.type === "ObjectExpression") returns.push({ stmt: n, obj: arg, fallback: inCatch });
        return;
      }
      if ((n.type === "ArrowFunctionExpression" || n.type === "FunctionExpression" || n.type === "FunctionDeclaration") && n !== fn) return;
      for (const c of children(n)) walk(c, inCatch || n.type === "CatchClause");
    };
    walk(fn.body, false);
  }
  return { fn, returns, propsType: fn ? propsTypeOf(ast, fn) : null };
}

/** The object type `load` promises — `Promise<DashboardProps>` resolved to
 *  the interface or type literal that declares it, so a key added to the
 *  data can be declared too. Null when the type is not written down here. */
function propsTypeOf(ast, fn) {
  let t = fn.returnType && fn.returnType.typeAnnotation;
  if (!t) return null;
  if (t.type === "TSTypeReference" && t.typeName.type === "Identifier" && t.typeName.name === "Promise"
      && t.typeParameters && t.typeParameters.params.length) t = t.typeParameters.params[0];
  if (t.type === "TSTypeLiteral") return { members: t.members, start: t.start, end: t.end };
  if (t.type !== "TSTypeReference" || t.typeName.type !== "Identifier") return null;
  const name = t.typeName.name;
  for (const s of ast.program.body) {
    const d = s.type === "ExportNamedDeclaration" ? s.declaration : s;
    if (!d) continue;
    if (d.type === "TSInterfaceDeclaration" && d.id.name === name) return { members: d.body.body, start: d.body.start, end: d.body.end };
    if (d.type === "TSTypeAliasDeclaration" && d.id.name === name && d.typeAnnotation.type === "TSTypeLiteral") {
      return { members: d.typeAnnotation.members, start: d.typeAnnotation.start, end: d.typeAnnotation.end };
    }
  }
  return null;
}

function memberNamed(members, key) {
  return members.find((mb) => mb.type === "TSPropertySignature" && mb.key && (mb.key.name ?? mb.key.value) === key) || null;
}

function model(view, load) {
  SRC = view;
  const ast = parseTsx(view);
  const nodes = {};
  const roots = jsxRoots(ast).map((r, i) => {
    const id = `r${i}`;
    buildNode(view, { node: r.node, container: null, context: null }, id, null, nodes, i);
    return { id, owner: r.owner ?? null };
  });
  return { ok: true, roots, nodes, imports: importsOf(view, ast), loadKeys: loadKeys(load), loadShapes: loadShapes(load), viewProps: viewProps(ast), viewParam: viewParam(ast) };
}

// ---------------------------------------------------------------------------
// Patching — every op re-parses, so its spans are exact
// ---------------------------------------------------------------------------

class PatchError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

function splice(source, start, end, text) {
  return source.slice(0, start) + text + source.slice(end);
}

function need(m, id) {
  const n = m.nodes[id];
  if (!n) throw new PatchError("missing-target", `There is nothing on the page with id ${id} any more — it may have been removed or the page changed.`);
  return n;
}

function jsxText(text) {
  return /[{}<>&]/.test(text) ? `{${JSON.stringify(text)}}` : text;
}

function attrText(name, value) {
  if (value == null || value.kind === "true") return name;
  if (value.kind === "string") return `${name}="${String(value.value).replace(/"/g, "&quot;")}"`;
  if (value.kind === "expr" || value.kind === "jsx") return `${name}={${value.value}}`;
  throw new PatchError("bad-value", `Unknown value kind ${value.kind}`);
}

/** A node's source with its own indentation taken off the continuation
 *  lines, so it can be put down anywhere at a new depth. */
function sourceOf(source, n) {
  return spanSource(source, removeSpan(n));
}
function spanSource(source, span) {
  const [s, e] = span;
  const own = lineIndent(source, s);
  return source.replace(/\r\n/g, "\n").slice(s, e).split("\n")
    .map((l, i) => (i === 0 || !own ? l : l.startsWith(own) ? l.slice(own.length) : l.replace(/^\s*/, (ws) => ws.slice(Math.min(ws.length, own.length)))))
    .join("\n");
}

function indentSnippet(snippet, indent) {
  const lines = snippet.replace(/\r\n/g, "\n").replace(/\n+$/, "").split("\n");
  return lines.map((l, i) => (i === 0 ? l : indent + l)).join("\n");
}

function opSetText(source, m, op) {
  const n = need(m, op.id);
  if (n.innerSpan == null) {
    // `<p />` becomes `<p>text</p>`
    const open = source.slice(n.span[0], n.span[1]).replace(/\s*\/>$/, ">");
    return splice(source, n.span[0], n.span[1], `${open}${jsxText(op.text)}</${n.type}>`);
  }
  if (!n.textEditable)
    throw new PatchError("mixed-text", `The text of this ${n.type} comes partly from data, so it cannot be typed over — ask Smith to change it.`);
  return splice(source, n.innerSpan[0], n.innerSpan[1], jsxText(op.text));
}

function opSetProp(source, m, op) {
  const n = need(m, op.id);
  if (n.kind === "fragment") throw new PatchError("no-props", "A fragment has no settings.");
  const existing = n.props.find((p) => p.name === op.name && p.kind !== "spread");
  if (op.value == null) {
    if (!existing) return source;
    // Take the attribute and the whitespace before it.
    let start = existing.span[0];
    while (start > 0 && /\s/.test(source[start - 1])) start--;
    return splice(source, start, existing.span[1], "");
  }
  const text = attrText(op.name, op.value);
  if (existing) return splice(source, existing.span[0], existing.span[1], text);
  // After the tag name (and any type arguments): `<Button` → `<Button name=…`
  const openStart = n.span[0];
  const tagEnd = openStart + 1 + n.type.length;
  let at = tagEnd;
  if (source[at] === "<") { // generic arguments: <Table<Row> …>
    let depth = 0;
    for (; at < source.length; at++) {
      if (source[at] === "<") depth++;
      else if (source[at] === ">") { depth--; if (depth === 0) { at++; break; } }
    }
  }
  return splice(source, at, at, ` ${text}`);
}

function classLiteralSpan(source, m, n) {
  // Where the static class string lives, whatever shape className takes.
  const attr = n.props.find((p) => p.name === "className" && p.kind !== "spread");
  if (!attr) return { attr: null };
  if (attr.kind === "string" && attr.valueSpan) {
    const raw = source.slice(attr.valueSpan[0], attr.valueSpan[1]);
    if (raw.startsWith('"') || raw.startsWith("'")) return { attr, span: [attr.valueSpan[0] + 1, attr.valueSpan[1] - 1] };
    // {"..."} or {`...`}
    const inner = raw.slice(1, -1).trim();
    const off = attr.valueSpan[0] + 1 + raw.slice(1, -1).indexOf(inner);
    return { attr, span: [off + 1, off + inner.length - 1] };
  }
  if (attr.kind === "expr") {
    const raw = attr.value;
    // cn("static …", cond && "x") / clsx(…) / twMerge(…): the first string literal.
    const call = /^(cn|clsx|twMerge|classNames)\(\s*(["'`])/.exec(raw);
    if (call) {
      const q = call[2];
      const litStart = attr.valueSpan[0] + 1 + call[0].length; // after the quote
      const litEnd = source.indexOf(q, litStart);
      if (litEnd > litStart && (q !== "`" || !source.slice(litStart, litEnd).includes("${"))) return { attr, span: [litStart, litEnd] };
    }
    return { attr, dynamic: true };
  }
  return { attr, dynamic: true };
}

function opSetClasses(source, m, op) {
  const n = need(m, op.id);
  const found = classLiteralSpan(source, m, n);
  const classes = String(op.classes).trim().replace(/\s+/g, " ");
  if (!found.attr) return opSetProp(source, m, { id: op.id, name: "className", value: { kind: "string", value: classes } });
  if (found.dynamic)
    throw new PatchError("dynamic-classes", `The look of this ${n.type} is decided by code at runtime, so it cannot be restyled here — ask Smith to change it.`);
  return splice(source, found.span[0], found.span[1], classes);
}

function removeSpan(n) {
  return n.wrapperSpan ?? n.span;
}

function cutWithLine(source, start, end) {
  // Remove the span; if its line is then blank, remove the line too.
  let s = start;
  while (s > 0 && (source[s - 1] === " " || source[s - 1] === "\t")) s--;
  let e = end;
  while (e < source.length && (source[e] === " " || source[e] === "\t")) e++;
  const lineEmpty = (s === 0 || source[s - 1] === "\n") && (e === source.length || source[e] === "\n");
  if (lineEmpty && s > 0) s--; // take the preceding newline
  return lineEmpty ? splice(source, s, e, "") : splice(source, start, end, "");
}

function opRemove(source, m, op) {
  const ids = op.ids ?? [op.id];
  const spans = ids.map((id) => removeSpan(need(m, id))).sort((a, b) => b[0] - a[0]);
  for (const [s, e] of spans) source = cutWithLine(source, s, e);
  return source;
}

function insertInto(source, m, parentId, index, snippet) {
  const p = need(m, parentId);
  if (p.kind === "element" && VOID_TAGS.has(p.type))
    throw new PatchError("cannot-contain", `A ${describe(p.type)} cannot hold other things.`);
  if (p.selfClosing) {
    const openEnd = p.span[1];
    const open = source.slice(p.span[0], openEnd).replace(/\s*\/>$/, ">");
    const indent = lineIndent(source, p.span[0]);
    const body = `\n${indent}  ${indentSnippet(snippet, indent + "  ")}\n${indent}`;
    return splice(source, p.span[0], openEnd, `${open}${body}</${p.type}>`);
  }
  const kids = p.children.map((cid) => m.nodes[cid]);
  const at = index == null ? kids.length : Math.max(0, Math.min(index, kids.length));
  if (at < kids.length) {
    const ref = kids[at];
    const refStart = ref.wrapperSpan ? ref.wrapperSpan[0] : ref.span[0];
    const indent = lineIndent(source, refStart);
    return splice(source, refStart, refStart, `${indentSnippet(snippet, indent)}\n${indent}`);
  }
  const closeIndent = lineIndent(source, p.innerSpan[1]);
  const childIndent = closeIndent + "  ";
  const lastEnd = kids.length ? (kids[kids.length - 1].wrapperSpan ?? kids[kids.length - 1].span)[1] : null;
  if (lastEnd != null) {
    return splice(source, lastEnd, lastEnd, `\n${childIndent}${indentSnippet(snippet, childIndent)}`);
  }
  // Empty element: `<div></div>` or `<div>\n</div>`
  const inner = source.slice(p.innerSpan[0], p.innerSpan[1]);
  const indent = lineIndent(source, p.span[0]);
  if (inner.trim() === "") return splice(source, p.innerSpan[0], p.innerSpan[1], `\n${indent}  ${indentSnippet(snippet, indent + "  ")}\n${indent}`);
  return splice(source, p.innerSpan[1], p.innerSpan[1], `\n${childIndent}${indentSnippet(snippet, childIndent)}\n${closeIndent}`);
}

function opInsert(source, m, op) {
  if (op.afterId || op.beforeId) {
    const ref = need(m, op.afterId ?? op.beforeId);
    if (ref.parent == null) throw new PatchError("no-parent", "Nothing can be placed beside the page itself — place it inside.");
    const idx = ref.index + (op.afterId ? 1 : 0);
    return insertInto(source, m, ref.parent, idx, op.jsx);
  }
  return insertInto(source, m, op.parentId, op.index, op.jsx);
}

function isAncestor(m, maybeAncestor, id) {
  let cur = m.nodes[id];
  while (cur && cur.parent != null) {
    if (cur.parent === maybeAncestor) return true;
    cur = m.nodes[cur.parent];
  }
  return false;
}

function opMove(source, m, op) {
  const n = need(m, op.id);
  need(m, op.parentId);
  if (op.parentId === op.id || isAncestor(m, op.id, op.parentId))
    throw new PatchError("circular", "Something cannot be moved inside itself.");
  const span = removeSpan(n);
  const snippet = sourceOf(source, n);
  // Insert first when the destination is before the cut, so spans stay valid;
  // otherwise cut first and re-model.
  let index = op.index ?? null;
  if (n.parent === op.parentId && index != null && index > n.index) index -= 1;
  const cut = cutWithLine(source, span[0], span[1]);
  const m2 = model(cut, null);
  return insertInto(cut, m2, op.parentId, index, snippet);
}

function opDuplicate(source, m, op) {
  const n = need(m, op.id);
  if (n.parent == null) throw new PatchError("no-parent", "The page itself cannot be duplicated.");
  return insertInto(source, m, n.parent, n.index + 1, sourceOf(source, n));
}

function opReplaceNode(source, m, op) {
  const n = need(m, op.id);
  const indent = lineIndent(source, n.span[0]);
  return splice(source, n.span[0], n.span[1], indentSnippet(op.jsx, indent));
}

function localOf(name) {
  // "default:Link" and "*:ns" bind the name after the colon.
  return name.includes(":") ? name.slice(name.indexOf(":") + 1) : name;
}

function opAddImport(source, m, op) {
  // A name already bound by ANY import stays as it is — the page may take
  // `widgets` from "@/sdk/widgets" rather than "@/sdk", and a second binding
  // would not parse. A type-only import (`typeOnly`) is satisfied by a
  // type-only binding as well.
  const typeOnly = !!op.typeOnly;
  const bound = new Set(m.imports.filter((i) => typeOnly || !i.typeOnly).flatMap((i) => i.names.map(localOf)));
  const names = (op.names ?? []).filter((nm) => nm && !bound.has(localOf(nm)));
  if (!names.length) return source;
  const existing = m.imports.find((i) => i.source === op.source && !!i.typeOnly === typeOnly);
  if (existing) {
    const missing = names.filter((nm) => !existing.names.includes(nm));
    if (!missing.length) return source;
    const raw = source.slice(existing.span[0], existing.span[1]);
    const brace = raw.lastIndexOf("}");
    if (brace < 0) throw new PatchError("import-shape", `Cannot extend the import from ${op.source}.`);
    const before = raw.slice(0, brace).replace(/\s*,?\s*$/, "");
    const spaced = before.endsWith("{") ? before + " " : before + ", ";
    return splice(source, existing.span[0], existing.span[1], `${spaced}${missing.join(", ")} ${raw.slice(brace)}`);
  }
  const defaults = names.filter((n) => n.startsWith("default:")).map(localOf);
  const named = names.filter((n) => !n.includes(":"));
  const clause = [defaults[0], named.length ? `{ ${named.join(", ")} }` : ""].filter(Boolean).join(", ");
  const line = `import ${typeOnly ? "type " : ""}${clause} from "${op.source}";\n`;
  const last = m.imports.length ? m.imports[m.imports.length - 1] : null;
  if (last) {
    let at = last.span[1];
    if (source[at] === "\n") at++;
    return splice(source, at, at, line);
  }
  // After "use client" if present.
  const m2 = /^(\s*["']use client["'];?\s*\n)/.exec(source);
  const at = m2 ? m2[0].length : 0;
  return splice(source, at, at, (m2 ? "\n" : "") + line);
}

function opEnsureProp(source, m, op) {
  // The View must be able to reach a key `load()` returns: add it to a
  // destructured parameter; a plain `props` parameter reaches it already.
  const ast = parseTsx(source);
  const p = viewParam(ast);
  if (!p) throw new PatchError("no-view", "This page has no View the editor can extend — ask Smith.");
  if (p.kind === "identifier") return source;
  if (p.kind === "none") throw new PatchError("no-props", "This page does not take its data in a way the editor can extend — ask Smith to connect it.");
  if (p.names.includes(op.name)) return source;
  const [start, end] = p.span;
  const raw = source.slice(start, end);
  const brace = raw.lastIndexOf("}");
  const before = raw.slice(0, brace).replace(/\s*,?\s*$/, "");
  const inner = before.endsWith("{") ? `${before} ${op.name} ` : `${before}, ${op.name} `;
  return splice(source, start, end, inner + raw.slice(brace));
}

const VOID_TAGS = new Set(["input", "img", "br", "hr", "textarea", "select"]);

function describe(tag) {
  return { input: "field", img: "image", br: "line break", hr: "divider", textarea: "text area", select: "dropdown" }[tag] ?? tag;
}

function opSetChildren(source, m, op) {
  // The element's content as raw JSX — text with data in it, or a single expression.
  const n = need(m, op.id);
  if (n.innerSpan == null) {
    const open = source.slice(n.span[0], n.span[1]).replace(/\s*\/>$/, ">");
    return splice(source, n.span[0], n.span[1], `${open}${op.jsx}</${n.type}>`);
  }
  return splice(source, n.innerSpan[0], n.innerSpan[1], op.jsx);
}

function objectSource(entries, indent) {
  // Entries back to a literal: short ones on a line, nested ones spread out.
  const inner = indent + "  ";
  const parts = entries.map((e) => {
    if (e.kind === "spread") return `${inner}${e.code}`;
    const key = /^[A-Za-z_$][\w$]*$/.test(e.key) ? e.key : JSON.stringify(e.key);
    if (e.kind === "object") return `${inner}${key}: ${objectSource(e.entries || [], inner)}`;
    if (e.kind === "objects") return `${inner}${key}: [${(e.items || []).map((it) => objectSource(it, inner)).join(", ")}]`;
    if (e.kind === "string") return `${inner}${key}: ${JSON.stringify(e.value ?? "")}`;
    if (e.kind === "strings") return `${inner}${key}: [${(e.value || []).map((v) => JSON.stringify(v)).join(", ")}]`;
    if (e.kind === "number" || e.kind === "boolean") return `${inner}${key}: ${String(e.value)}`;
    return `${inner}${key}: ${e.code}`;
  });
  if (!parts.length) return "{}";
  const oneLine = parts.map((p) => p.trim()).join(", ");
  if (oneLine.length < 70 && !parts.some((p) => p.includes("\n"))) return `{ ${oneLine} }`;
  return `{\n${parts.join(",\n")},\n${indent}}`;
}

function opSetObjectProp(source, m, op) {
  const n = need(m, op.id);
  const indent = lineIndent(source, n.span[0]);
  const literal = objectSource(op.entries || [], indent + "  ");
  return opSetProp(source, m, { id: op.id, name: op.name, value: { kind: "expr", value: literal } });
}

function opWrapCondition(source, m, op) {
  // Show the element only when `expr` holds: `{expr && (<X/>)}`; a wrapped one
  // gets its condition replaced.
  const n = need(m, op.id);
  if (n.parent == null) throw new PatchError("no-parent", "The page itself is always shown.");
  if (n.wrapperSpan && n.condition) {
    const [ws] = n.wrapperSpan;
    const condStart = ws + 1;
    const condEnd = condStart + n.condition.length;
    return splice(source, condStart, condEnd, op.expr);
  }
  if (n.wrapperSpan) throw new PatchError("in-expression", "This is part of a list or a choice already — ask Smith to add a condition to it.");
  const indent = lineIndent(source, n.span[0]);
  const body = indentSnippet(sourceOf(source, n), indent + "  ");
  return splice(source, n.span[0], n.span[1], `{${op.expr} && (\n${indent}  ${body}\n${indent})}`);
}

function opWrapRepeat(source, m, op) {
  // One of the element per item of `source`: `{source.map((row) => (<X key={row.id}>…</X>))}`.
  // An element already repeated has its source replaced.
  const n = need(m, op.id);
  if (n.parent == null) throw new PatchError("no-parent", "The page itself cannot be repeated.");
  const variable = op.variable || "row";
  if (n.wrapperSpan && n.repeat) {
    const [ws] = n.wrapperSpan;
    const start = ws + 1;
    return splice(source, start, start + n.repeat.source.length, op.source);
  }
  if (n.wrapperSpan) throw new PatchError("in-expression", "This is shown under a condition — take that off first, then repeat it.");
  const indent = lineIndent(source, n.span[0]);
  let body = sourceOf(source, n);
  if (!n.props.some((p) => p.name === "key")) {
    const open = /^<([A-Za-z][\w.]*)/.exec(body);
    if (open) body = body.slice(0, open[0].length) + ` key={${variable}.id}` + body.slice(open[0].length);
  }
  return splice(source, n.span[0], n.span[1], `{${op.source}.map((${variable}) => (\n${indent}  ${indentSnippet(body, indent + "  ")}\n${indent}))}`);
}

function opUnwrapRepeat(source, m, op) {
  // The element stands once again; the key that named its row goes with the row.
  const n = need(m, op.id);
  if (!n.wrapperSpan || !n.repeat) return source;
  const [ws, we] = n.wrapperSpan;
  const indent = lineIndent(source, ws);
  let body = spanSource(source, n.span);
  const key = n.props.find((p) => p.name === "key" && p.span);
  if (key && n.repeat.variable && String(key.value || "").startsWith(n.repeat.variable)) {
    const ks = key.span[0] - n.span[0], ke = key.span[1] - n.span[0];
    body = body.slice(0, ks).replace(/\s+$/, "") + body.slice(ke);
  }
  return splice(source, ws, we, indentSnippet(body, indent));
}

function opWrap(source, m, op) {
  // Siblings put inside a new container, in their order, where the first
  // one stood. `open`/`close` are the container's lines, relative; the
  // children sit one level in per line of `open`.
  const nodes = (op.ids || []).map((id) => need(m, id));
  if (!nodes.length) throw new PatchError("nothing", "Select what to group first.");
  const parent = nodes[0].parent;
  if (parent == null) throw new PatchError("no-parent", "The page itself cannot be grouped.");
  if (nodes.some((n) => n.parent !== parent)) throw new PatchError("not-siblings", "Group things that sit next to each other in the same container.");
  nodes.sort((a, b) => a.index - b.index);
  const first = removeSpan(nodes[0]);
  const indent = lineIndent(source, first[0]);
  const depth = String(op.open).split("\n").length;
  const inner = indent + "  ".repeat(depth);
  const body = nodes.map((n) => indentSnippet(sourceOf(source, n), inner)).join(`\n${inner}`);
  const wrapped = `${indentSnippet(op.open, indent)}\n${inner}${body}\n${indent}${indentSnippet(op.close, indent)}`;
  let out = source;
  // The later siblings go first (their offsets sit past the first one's).
  for (const [s, e] of nodes.slice(1).map((n) => removeSpan(n)).sort((a, b) => b[0] - a[0])) out = cutWithLine(out, s, e);
  return splice(out, first[0], first[1], wrapped);
}

function opUnwrap(source, m, op) {
  // A container's children take its place; the container goes.
  const n = need(m, op.id);
  if (n.parent == null) throw new PatchError("no-parent", "The page itself cannot be ungrouped.");
  if (!n.children.length) throw new PatchError("empty", "There is nothing inside it to keep — remove it instead.");
  if (n.wrapperSpan) throw new PatchError("in-expression", "This is shown under a condition or as part of a list — take that off first.");
  // Text of its own between the children would be lost; say so.
  let rest = source.slice(n.innerSpan[0], n.innerSpan[1]);
  for (const cid of [...n.children].reverse()) {
    const [s, e] = removeSpan(m.nodes[cid]);
    rest = rest.slice(0, s - n.innerSpan[0]) + rest.slice(e - n.innerSpan[0]);
  }
  if (rest.replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, "").trim()) throw new PatchError("has-text", "This holds text of its own as well as the things inside it — ask Smith to take it apart.");
  const indent = lineIndent(source, n.span[0]);
  const parts = n.children.map((cid) => indentSnippet(sourceOf(source, m.nodes[cid]), indent));
  return splice(source, n.span[0], n.span[1], parts.join(`\n${indent}`));
}

function opUnwrapCondition(source, m, op) {
  const n = need(m, op.id);
  if (!n.wrapperSpan || !n.condition) return source;
  const [ws, we] = n.wrapperSpan;
  const indent = lineIndent(source, ws);
  return splice(source, ws, we, indentSnippet(source.slice(n.span[0], n.span[1]), indent));
}

const OPS = {
  wrap: opWrap,
  unwrap: opUnwrap,
  wrapRepeat: opWrapRepeat,
  unwrapRepeat: opUnwrapRepeat,
  wrapCondition: opWrapCondition,
  unwrapCondition: opUnwrapCondition,
  setChildren: opSetChildren,
  setObjectProp: opSetObjectProp,
  setText: opSetText,
  setProp: opSetProp,
  setClasses: opSetClasses,
  remove: opRemove,
  insert: opInsert,
  move: opMove,
  duplicate: opDuplicate,
  replaceNode: opReplaceNode,
  addImport: opAddImport,
  ensureProp: opEnsureProp,
};

// ---------------------------------------------------------------------------
// load.ts — what the page reads, as ops on its `return { … }`
// ---------------------------------------------------------------------------

function loadModel(source) {
  const ast = parseTsx(source);
  return { imports: importsOf(source, ast), ...loadModelFromAst(ast) };
}

function needLoad(m) {
  if (!m.fn) throw new PatchError("no-load", "This page has no `load` the editor can extend — ask Smith.");
  if (!m.returns.length) throw new PatchError("load-shape", "What this page loads is not written in a way the editor can extend — ask Smith to add it.");
}

function opAddReturnKey(source, m, op) {
  needLoad(m);
  // Every `return { … }` of load gets the key, so the page's data has one
  // shape; a `catch` return gets the fallback value when one is given.
  const edits = [];
  for (const { stmt, obj, fallback } of m.returns) {
    const expr = fallback && op.fallback ? op.fallback : op.expr;
    const existing = obj.properties.find((p) => p.type === "ObjectProperty" && (p.key.name ?? p.key.value) === op.key);
    if (existing) { edits.push([existing.value.start, existing.value.end, expr]); continue; }
    const props = obj.properties;
    if (!props.length) {
      const indent = lineIndent(source, stmt.start);
      edits.push([obj.start, obj.end, `{\n${indent}  ${op.key}: ${expr},\n${indent}}`]);
      continue;
    }
    const last = props[props.length - 1];
    const indent = lineIndent(source, last.start);
    edits.push([last.end, last.end, `,\n${indent}${op.key}: ${expr}`]);
  }
  // The declared props type says the key is there too, when the page has one.
  const pt = m.propsType;
  if (pt && op.type) {
    const existing = memberNamed(pt.members, op.key);
    if (existing && existing.typeAnnotation) {
      edits.push([existing.typeAnnotation.typeAnnotation.start, existing.typeAnnotation.typeAnnotation.end, op.type]);
    } else if (!existing) {
      const last = pt.members[pt.members.length - 1];
      const indent = last ? lineIndent(source, last.start) : lineIndent(source, pt.start) + "  ";
      const close = pt.end - 1;
      const nl = source[close - 1] === "\n" ? "" : "\n";
      edits.push([close, close, `${nl}${indent}${op.key}: ${op.type};\n${indent.slice(0, Math.max(0, indent.length - 2))}`]);
    }
  }
  edits.sort((a, b) => b[0] - a[0]);
  for (const [s, e, text] of edits) source = splice(source, s, e, text);
  const typeName = op.type && /^[A-Za-z_$][\w$]*/.exec(op.type);
  if (pt && typeName && op.typeSource) {
    source = opAddImport(source, loadModel(source), { source: op.typeSource, names: [typeName[0]], typeOnly: true });
  }
  return source;
}

function opRemoveReturnKey(source, m, op) {
  needLoad(m);
  const edits = [];
  for (const { obj } of m.returns) {
    const i = obj.properties.findIndex((p) => p.type === "ObjectProperty" && (p.key.name ?? p.key.value) === op.key);
    if (i < 0) continue;
    const p = obj.properties[i];
    let end = p.end;
    const after = source.slice(end, obj.end);
    const comma = /^\s*,/.exec(after);
    if (comma) end += comma[0].length;
    edits.push([p.start, end]);
  }
  const mb = m.propsType ? memberNamed(m.propsType.members, op.key) : null;
  if (mb) {
    let end = mb.end;
    const after = source.slice(end, m.propsType.end);
    const sep = /^\s*[;,]/.exec(after);
    if (sep && !/\n/.test(sep[0])) end += sep[0].length;
    edits.push([mb.start, end]);
  }
  edits.sort((a, b) => b[0] - a[0]);
  for (const [s, e] of edits) source = cutWithLine(source, s, e);
  return source;
}

const LOAD_OPS = { addReturnKey: opAddReturnKey, removeReturnKey: opRemoveReturnKey, addImport: opAddImport, setReadOptions: opSetReadOptions };

function patchLoad(load, ops) {
  let source = load;
  for (const op of ops) {
    const fn = LOAD_OPS[op.op];
    if (!fn) throw new PatchError("unknown-op", `Unknown load operation ${op.op}`);
    source = fn(source, loadModel(source), op);
  }
  try { parseTsx(source); } catch (e) { throw new PatchError("syntax", `The change would leave what the page loads unreadable: ${e.message}`); }
  return { ok: true, load: source, applied: ops.map((o) => o.op) };
}

function patch(view, ops) {
  let source = view;
  const applied = [];
  for (const op of ops) {
    const fn = OPS[op.op];
    if (!fn) throw new PatchError("unknown-op", `Unknown operation ${op.op}`);
    const m = model(source, null);
    source = fn(source, m, op);
    applied.push(op.op);
  }
  try {
    parseTsx(source);
  } catch (e) {
    throw new PatchError("syntax", `The change would leave the page unreadable: ${e.message}`);
  }
  return { ok: true, view: source, applied };
}

// ---------------------------------------------------------------------------
// Annotation — the running app's copy carries the ids, the Blueprint's does not
// ---------------------------------------------------------------------------

function annotate(view) {
  const m = model(view, null);
  const inserts = [];
  for (const n of Object.values(m.nodes)) {
    if (n.kind === "fragment") continue;
    if (n.props.some((p) => p.name === "data-fid")) continue;
    const tagEnd = n.span[0] + 1 + n.type.length;
    let at = tagEnd;
    if (view[at] === "<") {
      let depth = 0;
      for (; at < view.length; at++) {
        if (view[at] === "<") depth++;
        else if (view[at] === ">") { depth--; if (depth === 0) { at++; break; } }
      }
    }
    inserts.push([at, ` data-fid="${n.id}"`]);
  }
  inserts.sort((a, b) => b[0] - a[0]);
  let out = view;
  for (const [at, text] of inserts) out = splice(out, at, at, text);
  return { ok: true, view: out };
}

// ---------------------------------------------------------------------------

async function main() {
  const cmd = process.argv[2];
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  try {
    let out;
    if (cmd === "model") out = model(input.view ?? "", input.load ?? null);
    else if (cmd === "patch") out = patch(input.view ?? "", input.ops ?? []);
    else if (cmd === "patchLoad") out = patchLoad(input.load ?? "", input.ops ?? []);
    else if (cmd === "annotate") out = annotate(input.view ?? "");
    else if (cmd === "samples") out = { ok: true, rows: Object.fromEntries((input.entities || []).map((e) => [e.name, Array.from({ length: 8 }, (_, i) => sampleRow(e, i, input.entities))])) };
    else throw new PatchError("usage", `unknown command ${cmd}`);
    process.stdout.write(JSON.stringify(out));
  } catch (e) {
    const code = e instanceof PatchError ? e.code : (e.name === "SyntaxError" ? "syntax" : "internal");
    const line = e.loc ? e.loc.line : null;
    process.stdout.write(JSON.stringify({ ok: false, error: { code, message: e.message, line } }));
    process.exitCode = 2;
  }
}

main();
