import { z } from "zod";
import { CustomNode } from "@tentoroforge/schema";
export const CustomBlockProps = CustomNode.shape.props;
export type CustomBlockPropsType = z.infer<typeof CustomBlockProps>;
