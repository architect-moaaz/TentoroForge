// packages/library/src/components/Chart/Chart.schema.ts
import { z } from "zod";
import { ChartNode } from "@tentoroforge/schema";

export const ChartProps = ChartNode.shape.props;
export type ChartPropsType = z.infer<typeof ChartProps>;
