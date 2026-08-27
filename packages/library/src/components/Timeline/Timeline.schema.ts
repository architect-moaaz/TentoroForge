import { z } from "zod";
import { TimelineNode } from "@tentoroforge/schema";
export const TimelineProps = TimelineNode.shape.props;
export type TimelinePropsType = z.infer<typeof TimelineProps>;
