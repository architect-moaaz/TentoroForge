import { z } from "zod";
import { FeatureCardNode } from "@tentoroforge/schema";
export const FeatureCardProps = FeatureCardNode.shape.props;
export type FeatureCardPropsType = z.infer<typeof FeatureCardProps>;
