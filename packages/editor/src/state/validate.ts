import { Page } from "@tentoroforge/schema";
import type { ValidationError } from "./types";

export function validateSchema(input: unknown): ValidationError[] {
  const result = Page.safeParse(input);
  if (result.success) return [];
  return result.error.errors.map((e) => ({
    path: e.path,
    message: e.message,
    code: e.code,
  }));
}
