import fs from "fs";
import path from "path";

export function loadCustomTokens(): Record<string, Record<string, string>> | null {
  const p = path.resolve(process.cwd(), "src/theme/tokens.custom.json");
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}
