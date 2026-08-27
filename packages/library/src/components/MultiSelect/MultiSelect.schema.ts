import { z } from "zod";
import { MultiSelectNode } from "@tentoroforge/schema";
export const MultiSelectProps = MultiSelectNode.shape.props;
export type MultiSelectPropsType = z.infer<typeof MultiSelectProps>;
