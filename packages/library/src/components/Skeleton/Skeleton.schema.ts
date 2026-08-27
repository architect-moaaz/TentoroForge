import { z } from "zod";
import { SkeletonNode } from "@tentoroforge/schema";
export const SkeletonProps = SkeletonNode.innerType().shape.props;
export type SkeletonPropsType = z.infer<typeof SkeletonProps>;
