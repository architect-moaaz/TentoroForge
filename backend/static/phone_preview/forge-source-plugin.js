// Marks each element a phone screen draws with the file and line that wrote it, so the editor's bridge can say
// "this came from app/(tabs)/index.tsx:42". react-native-web turns `dataSet` into `data-*` attributes.
// Used only when the editor's phone preview is built; never part of a build that ships.
const path = require("path");

module.exports = function forgeSource({ types: t }) {
  const SCREEN = /[\\/](app|src[\\/]screens)[\\/]/;
  return {
    name: "forge-source",
    visitor: {
      JSXOpeningElement(p, state) {
        const file = state.filename || "";
        if (!SCREEN.test(file)) return;
        const name = p.node.name;
        if (name.type !== "JSXIdentifier" || !/^[A-Z]/.test(name.name) || name.name === "Fragment") return;
        if (p.node.attributes.some((a) => a.type === "JSXAttribute" && a.name && a.name.name === "dataSet")) return;
        const rel = path.relative(state.cwd || process.cwd(), file).split(path.sep).join("/");
        const line = p.node.loc ? String(p.node.loc.start.line) : "0";
        const str = (v) => t.stringLiteral(v);
        p.node.attributes.push(
          t.jsxAttribute(
            t.jsxIdentifier("dataSet"),
            t.jsxExpressionContainer(
              t.objectExpression([
                t.objectProperty(t.identifier("sourceFile"), str(rel)),
                t.objectProperty(t.identifier("sourceLine"), str(line)),
                t.objectProperty(t.identifier("sourceComponent"), str(name.name)),
              ]),
            ),
          ),
        );
      },
    },
  };
};
