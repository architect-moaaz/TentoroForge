/**
 * Compile a `row_access` rule's FEEL-lite condition into a SQL predicate.
 *
 * A row rule authored in the rules builder has to become a WHERE clause, not a
 * filter applied after the rows come back. Evaluating it per row in memory
 * would hide rows from the page while `total` still counted them, the pager
 * still offered them and every aggregate still summed them — a row that is
 * invisible in one place and present in three others is not access control,
 * it is a rendering trick.
 *
 * So the condition is parsed with the same FEEL-lite parser the rules engine
 * uses, and the AST is walked into Drizzle operators. The subset that compiles
 * is deliberately narrow:
 *
 *   comparison      status = "active",  amount >= 100,  ownerId = user.id
 *   membership      currentStage in ["offer", "hired"]
 *   range           createdAt between x and y
 *   combination     and / or / not, nested freely
 *   null            approvedAt = null
 *
 * Anything else — a function call, arithmetic, an if/then/else — returns
 * `{ ok: false, reason }` rather than a predicate. The caller decides what to
 * do with that, and the only safe answer is to refuse the read: a rule that
 * cannot be enforced must not quietly become a rule that is not enforced.
 *
 * A comparison against a `user.*` value the session does not carry compiles to
 * FALSE rather than failing. It is not a broken rule — it is a rule whose
 * subject is absent, and absent means no rows.
 */

import { tokenize, parse } from "../feel-lite";
import type { ASTNode } from "../feel-lite/ast";
import {
  and, or, not, eq, ne, lt, lte, gt, gte, inArray, isNull, isNotNull, sql,
  type SQL,
} from "drizzle-orm";

export type CompileResult =
  | { ok: true; where: SQL }
  | { ok: false; reason: string };

/** A resolved operand: a table column, a constant, or an absent user value. */
type Operand =
  | { kind: "column"; col: any; name: string }
  | { kind: "value"; value: unknown }
  | { kind: "absent"; path: string };

/** Raised internally so a deep rejection unwinds to one `{ok:false}`. */
class Uncompilable extends Error {}

function reject(reason: string): never {
  throw new Uncompilable(reason);
}

/** Always-false / always-true predicates, spelled so Postgres plans them. */
const FALSE = sql`false` as SQL;
const TRUE = sql`true` as SQL;

/**
 * Resolve one side of a comparison.
 *
 * A bare identifier is a column on the row — that is the whole point of a row
 * rule, and an identifier that is NOT a column is a typo the author should see
 * rather than a silently-null comparison that lets every row through.
 */
function operand(
  node: ASTNode,
  table: Record<string, any>,
  user: Record<string, unknown> | undefined,
): Operand {
  switch (node.type) {
    case "NumberLiteral":
    case "StringLiteral":
    case "BooleanLiteral":
      return { kind: "value", value: (node as any).value };
    case "NullLiteral":
      return { kind: "value", value: null };
    case "Identifier":
      // FEEL-lite tokenises a dotted path as ONE identifier, so `user.id` and
      // `status` arrive the same way and are told apart here.
      return named((node as any).name, table, user);
    case "MemberExpression": {
      // Kept for the shapes the parser does build as members.
      const { object, property } = node as any;
      const head = object?.type === "Identifier" ? object.name : null;
      if (!head) reject("only `user.<field>` may be reached through a dot");
      return named(`${head}.${property}`, table, user);
    }
    case "UnaryExpression": {
      const inner = operand((node as any).operand, table, user);
      if (inner.kind !== "value" || typeof inner.value !== "number") {
        reject("a sign may only be applied to a number literal");
      }
      return {
        kind: "value",
        value: (node as any).operator === "-" ? -inner.value : inner.value,
      };
    }
    case "FunctionCall":
      reject(`\`${(node as any).name}(…)\` cannot be compiled to SQL`);
      break;
    case "BinaryExpression":
      reject(`arithmetic (\`${(node as any).operator}\`) cannot be compiled to SQL`);
      break;
    case "IfExpression":
      reject("if/then/else cannot be compiled to SQL");
      break;
    default:
      reject(`\`${node.type}\` cannot be compiled to SQL`);
  }
  // Unreachable — every branch returns or rejects.
  return reject("unreachable");
}

/**
 * Resolve one dotted-or-plain name.
 *
 * `user.<field>` reads from the session; a bare name is a column of the row.
 * Anything else dotted — `order.total`, a join by another name — has no SQL
 * here: the predicate runs against one table, and quietly ignoring the
 * qualifier would compile a rule that means something else.
 */
function named(
  name: string,
  table: Record<string, any>,
  user: Record<string, unknown> | undefined,
): Operand {
  const dot = name.indexOf(".");
  if (dot === -1) {
    const col = table[name];
    if (col === undefined) {
      reject(
        `"${name}" is not a column on this entity — a row rule compares ` +
        `columns of the row against \`user.<field>\` or a constant`,
      );
    }
    return { kind: "column", col, name };
  }
  const head = name.slice(0, dot);
  const rest = name.slice(dot + 1);
  if (head !== "user") {
    reject(
      `\`${name}\` reaches outside the row — only \`user.<field>\` is available ` +
      `through a dot, because the predicate runs against one table`,
    );
  }
  // Nested session values (`user.profile.org`) are not addressable either.
  const v = rest.includes(".") ? undefined : user?.[rest];
  if (v === undefined || v === null || v === "") {
    return { kind: "absent", path: name };
  }
  return { kind: "value", value: v };
}

/** The mirror of a comparison, for `"active" = status` written backwards. */
const FLIP: Record<string, string> = {
  "=": "=", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<=",
};

function comparison(
  operator: string,
  left: Operand,
  right: Operand,
): SQL {
  // A user value the session does not carry can satisfy nothing.
  if (left.kind === "absent" || right.kind === "absent") return FALSE;

  // Normalise to column-on-the-left.
  if (left.kind === "value" && right.kind === "column") {
    return comparison(FLIP[operator], right, left);
  }
  if (left.kind !== "column") {
    reject("a comparison must name at least one column of the row");
  }

  // `x = null` is IS NULL in SQL; `x = NULL` is never true, which would make
  // the rule silently unsatisfiable.
  if (right.kind === "value" && right.value === null) {
    if (operator === "=") return isNull(left.col) as SQL;
    if (operator === "!=") return isNotNull(left.col) as SQL;
    reject(`\`${operator}\` against null has no meaning`);
  }

  const rhs = right.kind === "column" ? right.col : (right as any).value;
  switch (operator) {
    case "=":  return eq(left.col, rhs) as SQL;
    case "!=": return ne(left.col, rhs) as SQL;
    case "<":  return lt(left.col, rhs) as SQL;
    case "<=": return lte(left.col, rhs) as SQL;
    case ">":  return gt(left.col, rhs) as SQL;
    case ">=": return gte(left.col, rhs) as SQL;
    default:   return reject(`unknown comparison \`${operator}\``);
  }
}

function walk(
  node: ASTNode,
  table: Record<string, any>,
  user: Record<string, unknown> | undefined,
): SQL {
  switch (node.type) {
    case "BooleanLiteral":
      // `true` is how a rule says "this role sees every row" — the permissive
      // grant that keeps an unnamed role from being denied by default.
      return (node as any).value ? TRUE : FALSE;

    case "LogicalExpression": {
      const { operator, left, right } = node as any;
      const l = walk(left, table, user);
      const r = walk(right, table, user);
      return (operator === "and" ? and(l, r) : or(l, r)) as SQL;
    }

    case "NotExpression":
      return not(walk((node as any).operand, table, user)) as SQL;

    case "ComparisonExpression": {
      const { operator, left, right } = node as any;
      return comparison(
        operator,
        operand(left, table, user),
        operand(right, table, user),
      );
    }

    case "InExpression": {
      const { value, list } = node as any;
      const target = operand(value, table, user);
      if (target.kind === "absent") return FALSE;
      if (target.kind !== "column") reject("`in` must test a column of the row");
      if (list?.type === "ListExpression") {
        const items = (list.elements as ASTNode[]).map((e) => operand(e, table, user));
        if (items.some((i) => i.kind === "column")) {
          reject("`in` takes a list of constants, not columns");
        }
        const values = items
          .filter((i) => i.kind === "value")
          .map((i) => (i as any).value);
        // Every element was an absent user value → nothing can match.
        if (values.length === 0) return FALSE;
        return inArray(target.col, values as any) as SQL;
      }
      if (list?.type === "RangeExpression") {
        const { start, end, startInclusive, endInclusive } = list;
        const lo = operand(start, table, user);
        const hi = operand(end, table, user);
        if (lo.kind === "absent" || hi.kind === "absent") return FALSE;
        return and(
          (startInclusive ? gte : gt)(target.col, (lo as any).value),
          (endInclusive ? lte : lt)(target.col, (hi as any).value),
        ) as SQL;
      }
      return reject("`in` needs a list or a range on its right");
    }

    case "BetweenExpression": {
      const { value, low, high } = node as any;
      const target = operand(value, table, user);
      const lo = operand(low, table, user);
      const hi = operand(high, table, user);
      if (target.kind === "absent" || lo.kind === "absent" || hi.kind === "absent") {
        return FALSE;
      }
      if (target.kind !== "column") reject("`between` must test a column of the row");
      return and(
        gte(target.col, lo.kind === "column" ? lo.col : (lo as any).value),
        lte(target.col, hi.kind === "column" ? hi.col : (hi as any).value),
      ) as SQL;
    }

    // A bare column as the whole condition means "this boolean column is true".
    case "Identifier": {
      const o = operand(node, table, user);
      if (o.kind !== "column") reject("a condition must be a boolean expression");
      return eq(o.col, true as any) as SQL;
    }

    default: {
      // operand() carries the precise refusal for a function call, arithmetic
      // or an if/then/else; anything it accepts is a value standing where a
      // boolean belongs.
      operand(node, table, user);
      return reject("a condition must be a boolean expression");
    }
  }
}

/**
 * Compile `condition` against `table` for `user`.
 *
 * `table` is the Drizzle table object — its keys are the row's columns.
 * `user` is the acting session; a `user.*` reference it does not carry makes
 * the containing comparison false rather than failing the compile, because an
 * absent subject is a real state, not a broken rule.
 */
export function compileRowAccess(
  condition: string,
  table: Record<string, any>,
  user: Record<string, unknown> | undefined,
): CompileResult {
  const text = String(condition ?? "").trim();
  if (!text) return { ok: false, reason: "the condition is empty" };
  let ast: ASTNode;
  try {
    ast = parse(tokenize(text));
  } catch (e) {
    return { ok: false, reason: `could not be parsed: ${(e as Error).message}` };
  }
  try {
    return { ok: true, where: walk(ast, table, user) };
  } catch (e) {
    if (e instanceof Uncompilable) return { ok: false, reason: e.message };
    return { ok: false, reason: `could not be compiled: ${(e as Error).message}` };
  }
}
