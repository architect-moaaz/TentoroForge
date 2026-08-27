import { z } from "zod";
import { MetricTileNode } from "@tentoroforge/schema";
export const MetricTileProps = MetricTileNode.shape.props;
export type MetricTilePropsType = z.infer<typeof MetricTileProps>;
