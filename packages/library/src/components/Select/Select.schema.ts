import { z } from "zod";
import { SelectNode } from "@tentoroforge/schema";
export const SelectProps = SelectNode.shape.props;
export type SelectPropsType = z.infer<typeof SelectProps>;
