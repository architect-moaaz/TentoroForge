// packages/library/src/components/Sparkline/Sparkline.schema.ts
import { z } from "zod";
import { SparklineNode } from "@tentoroforge/schema";

export const SparklineProps = SparklineNode.shape.props;
export type SparklinePropsType = z.infer<typeof SparklineProps>;
