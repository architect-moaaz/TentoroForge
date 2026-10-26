// What each part of the phone kit lets a person choose, read from the kit's own types.
//
//   node kit-schema.mjs <kit folder> <toolchain folder> [<project folder>]   ->  JSON on stdout
//
// The TypeScript compiler is asked, not a list kept by hand: a prop whose type is a set of words (`variant: "primary" | "ghost"`,
// `gap: Space | number`) is a pick list with exactly those words, a prop that is `boolean` is a switch. Only props the kit itself
// declares are listed: the ones a component inherits from React Native (`style`, `testID`, ...) are not choices of the kit.
import { createRequire } from "node:module";
import path from "node:path";
import { existsSync } from "node:fs";

const [kitArg, toolchainArg, projectArg] = process.argv.slice(2);
const kit = path.resolve(kitArg);
const toolchain = path.resolve(toolchainArg);
const modules = path.join(toolchain, "node_modules");
const require = createRequire(path.join(toolchain, "x.js"));
const ts = require("typescript");

const index = path.join(kit, "index.ts");
const src = path.dirname(kit);
const options = {
  target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  jsx: ts.JsxEmit.ReactNative, strict: true, noEmit: true, skipLibCheck: true, allowJs: false, esModuleInterop: true,
  baseUrl: kit, typeRoots: [path.join(modules, "@types")], types: [],
  paths: { "@/*": [src.replace(/\\/g, "/") + "/*"], "*": [modules.replace(/\\/g, "/") + "/*", modules.replace(/\\/g, "/") + "/@types/*"] },
};
if (projectArg && existsSync(projectArg)) options.paths["@/*"] = [path.join(path.resolve(projectArg), "src").replace(/\\/g, "/") + "/*"];

const program = ts.createProgram([index], options);
const checker = program.getTypeChecker();
const sf = program.getSourceFile(index);
if (!sf) { console.log(JSON.stringify({ ok: false, error: "the kit's index.ts could not be read" })); process.exit(0); }

const inKit = (decl) => {
  const f = path.resolve(decl.getSourceFile().fileName);
  return f.startsWith(kit + path.sep) && !f.includes(`${path.sep}node_modules${path.sep}`);
};

function classify(type, node) {
  const parts = type.isUnion() ? type.types : [type];
  const real = parts.filter((t) => !(t.flags & (ts.TypeFlags.Undefined | ts.TypeFlags.Null | ts.TypeFlags.Void)));
  if (real.length === 0) return null;
  const words = real.filter((t) => t.isStringLiteral()).map((t) => t.value);
  const bools = real.filter((t) => t.flags & ts.TypeFlags.BooleanLiteral);
  const rest = real.filter((t) => !t.isStringLiteral() && !(t.flags & ts.TypeFlags.BooleanLiteral));
  if (bools.length && !words.length && !rest.length) return { kind: "boolean" };
  if (words.length && rest.every((t) => t.flags & ts.TypeFlags.Number)) return { kind: "enum", values: words, ...(rest.length ? { alsoNumber: true } : {}) };
  if (real.length === 1 && (real[0].flags & ts.TypeFlags.String)) return { kind: "string" };
  if (real.length === 1 && (real[0].flags & ts.TypeFlags.Number)) return { kind: "number" };
  return { kind: "other" };
}

const components = {};
for (const sym of checker.getExportsOfModule(checker.getSymbolAtLocation(sf))) {
  const name = sym.getName();
  if (!/^[A-Z]/.test(name)) continue;
  const target = sym.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(sym) : sym;
  const decl = target.valueDeclaration ?? target.declarations?.[0];
  if (!decl || !(target.flags & (ts.SymbolFlags.Function | ts.SymbolFlags.Variable))) continue;
  const sigs = checker.getTypeOfSymbolAtLocation(target, decl).getCallSignatures();
  if (!sigs.length || !sigs[0].getParameters().length) { components[name] = { props: {} }; continue; }
  const param = sigs[0].getParameters()[0];
  const propsType = checker.getTypeOfSymbolAtLocation(param, param.valueDeclaration ?? decl);
  const props = {};
  for (const p of propsType.getProperties()) {
    const d = p.valueDeclaration ?? p.declarations?.[0];
    if (!d || !inKit(d)) continue;
    const c = classify(checker.getTypeOfSymbolAtLocation(p, d), d);
    if (c) props[p.getName()] = { ...c, optional: !!(p.flags & ts.SymbolFlags.Optional) };
  }
  components[name] = { props };
}
console.log(JSON.stringify({ ok: true, components }));
