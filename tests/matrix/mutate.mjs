/**
 * MUTATION TESTING — calibrate the tester.
 *
 *   node tests/matrix/mutate.mjs apply
 *   node tests/matrix/mutate.mjs revert     (or: git checkout packages/library/src)
 *
 * Plants known defects in props that the sweep currently reports as WORKING.
 * Each mutation renames the destructured prop and shadows it with a constant, so
 * the component still renders but the prop is silently dead — the exact shape of
 * the real Cascader.placeholder and NavLink.icon defects.
 *
 * The sweep is then re-run. Every planted bug it FAILS to flip from WORKS to
 * NO-EFFECT is a measured blind spot. A suite that has never been shown to catch
 * a real defect is an untested tester, and its green results are an opinion.
 */
import { readFileSync, writeFileSync } from "node:fs";

const ROOT = "packages/library/src/components";

/** prop, the exact destructure to rewrite, and the constant that replaces it. */
const MUTANTS = [
  { comp: "Badge", prop: "content",
    from: "export function Badge({ content, variant, style }: Props) {",
    to:   "export function Badge({ content: _mut, variant, style }: Props) {\n  const content = \"Badge\";" },
  { comp: "Alert", prop: "variant",
    from: "export function Alert({ message, variant = \"neutral\", title, style }: Props) {",
    to:   "export function Alert({ message, variant: _mut = \"neutral\", title, style }: Props) {\n  const variant = \"neutral\" as typeof _mut;" },
  { comp: "Avatar", prop: "size",
    from: "export function Avatar({ src, photoUrl, name, size, status, style }: AvatarProps) {",
    to:   "export function Avatar({ src, photoUrl, name, size: _mut, status, style }: AvatarProps) {\n  const size = undefined as typeof _mut;" },
  { comp: "Heading", prop: "level",
    from: "export function Heading({ level = 2, content, id, weight, style, className: extraCn }: Props) {",
    to:   "export function Heading({ level: _mut = 2, content, id, weight, style, className: extraCn }: Props) {\n  const level = 2 as typeof _mut;" },
  { comp: "Skeleton", prop: "lines",
    from: "export function Skeleton({ variant, lines, style }: SkeletonProps) {",
    to:   "export function Skeleton({ variant, lines: _mut, style }: SkeletonProps) {\n  const lines = undefined as typeof _mut;" },
  { comp: "Tooltip", prop: "label",
    from: "export function Tooltip({ label, content, side = \"top\", style, children }: TooltipProps) {",
    to:   "export function Tooltip({ label: _mut, content, side = \"top\", style, children }: TooltipProps) {\n  const label = \"Tooltip\";" },
];

const mode = process.argv[2] ?? "apply";
if (mode !== "apply") {
  console.error("revert with: git checkout -- packages/library/src");
  process.exit(1);
}

let ok = 0;
for (const m of MUTANTS) {
  const path = `${ROOT}/${m.comp}/${m.comp}.tsx`;
  const src = readFileSync(path, "utf-8");
  if (!src.includes(m.from)) {
    console.error(`  !! ${m.comp}.${m.prop}: anchor not found — NOT mutated`);
    continue;
  }
  writeFileSync(path, src.replace(m.from, m.to), "utf-8");
  console.log(`  planted ${m.comp}.${m.prop}`);
  ok++;
}
console.log(`\n${ok}/${MUTANTS.length} mutations planted`);
writeFileSync("tests/matrix/mutants.json",
  JSON.stringify(MUTANTS.map((m) => `${m.comp}.${m.prop}`), null, 1), "utf-8");
