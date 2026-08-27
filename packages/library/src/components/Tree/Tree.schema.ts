import { z } from "zod";
export type TreeNodeT = { label: string; value?: string; children?: TreeNodeT[] };
const TreeNode: z.ZodType<TreeNodeT> = z.lazy(() =>
  z.object({ label: z.string(), value: z.string().optional(), children: z.array(TreeNode).optional() })
);
export const TreeProps = z.object({
  items:     z.array(TreeNode).default([]),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TreePropsType = z.infer<typeof TreeProps>;
