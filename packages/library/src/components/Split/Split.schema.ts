import { z } from "zod";
import { SplitNode } from "@tentoroforge/schema";
export const SplitProps = SplitNode.shape.props;
export type SplitPropsType = z.infer<typeof SplitProps>;
