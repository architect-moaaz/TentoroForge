import { z } from "zod";
import { TextareaNode } from "@tentoroforge/schema";
export const TextareaProps = TextareaNode.shape.props;
export type TextareaPropsType = z.infer<typeof TextareaProps>;
