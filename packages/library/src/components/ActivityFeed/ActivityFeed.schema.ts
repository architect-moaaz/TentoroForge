import { z } from "zod";
import { ActivityFeedNode } from "@tentoroforge/schema";
export const ActivityFeedProps = ActivityFeedNode.shape.props;
export type ActivityFeedPropsType = z.infer<typeof ActivityFeedProps>;
