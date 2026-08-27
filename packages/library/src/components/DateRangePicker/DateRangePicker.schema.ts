import { z } from "zod";
import { DateRangePickerNode } from "@tentoroforge/schema";
export const DateRangePickerProps = DateRangePickerNode.shape.props;
export type DateRangePickerPropsType = z.infer<typeof DateRangePickerProps>;
