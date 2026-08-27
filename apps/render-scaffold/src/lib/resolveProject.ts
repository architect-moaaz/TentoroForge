import path from "node:path";

const OUTPUT_ROOT = process.env.OUTPUT_ROOT
  ?? path.resolve(process.cwd(), "..", "..", "output");

export function resolveProject(projectId: string): string {
  if (!projectId) throw new Error("invalid project id: empty");
  if (projectId.includes("/") || projectId.includes("..") || projectId.startsWith(".")) {
    throw new Error(`invalid project id: ${projectId}`);
  }
  return path.join(OUTPUT_ROOT, projectId);
}
