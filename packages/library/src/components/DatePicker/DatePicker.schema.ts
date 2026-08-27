import { z } from "zod";
import { DatePickerNode } from "@tentoroforge/schema";
export const DatePickerProps = DatePickerNode.shape.props;
export type DatePickerPropsType = z.infer<typeof DatePickerProps>;
