// The words a screen shows, read from its code: every text between tags, every
// quoted string a tag shows (`{"Open"}`, `{done ? "Done" : "Open"}`) and the
// words of the attributes a person reads or hears (placeholder, title, alt,
// aria-label). Nothing a comparison, a class or a call takes.
//
// stdin: [{"id": string, "code": string}]   stdout: {"<id>": [string]}
import ts from "typescript";

const SPOKEN = new Set(["placeholder", "title", "alt", "aria-label", "label"]);

export function norm(s) {
  return String(s).replace(/\s+/g, " ").trim();
}

function worded(s) {
  return /\p{L}/u.test(s);
}

// A string literal is shown when the value of the expression it sits in is
// what the tag renders: itself, a branch of a choice, a fallback.
function shown(node) {
  let at = node;
  for (;;) {
    const up = at.parent;
    if (!up) return false;
    if (ts.isJsxExpression(up)) return !ts.isJsxAttribute(up.parent) || SPOKEN.has(up.parent.name.getText());
    if (ts.isParenthesizedExpression(up)) { at = up; continue; }
    if (ts.isConditionalExpression(up) && up.condition !== at) { at = up; continue; }
    if (ts.isBinaryExpression(up) && up.right === at && [ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken,
      ts.SyntaxKind.AmpersandAmpersandToken].includes(up.operatorToken.kind)) { at = up; continue; }
    return false;
  }
}

export function wordsOf(code) {
  const file = ts.createSourceFile("x.tsx", code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out = new Set();
  const add = (s) => { const n = norm(s); if (n && worded(n)) out.add(n); };
  const visit = (node) => {
    if (ts.isJsxText(node)) add(node.text);
    else if (ts.isJsxAttribute(node) && SPOKEN.has(node.name.getText()) && node.initializer && ts.isStringLiteral(node.initializer)) add(node.initializer.text);
    else if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && shown(node)) add(node.text);
    ts.forEachChild(node, visit);
  };
  visit(file);
  return [...out];
}

if (import.meta.url === `file://${process.argv[1]}`) {
  let input = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => { input += c; });
  process.stdin.on("end", () => {
    const out = {};
    for (const { id, code } of JSON.parse(input || "[]")) out[id] = wordsOf(String(code || ""));
    process.stdout.write(JSON.stringify(out));
  });
}
