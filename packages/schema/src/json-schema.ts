import { zodToJsonSchema } from "zod-to-json-schema";
import { Page } from "./page";

export function pageJsonSchema() {
  return zodToJsonSchema(Page, { target: "jsonSchema7" });
}
