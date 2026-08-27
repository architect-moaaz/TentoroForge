import { z } from "zod";
import { TabsNode } from "@tentoroforge/schema";
// TabsNode is wrapped in a refine() — its inner shape is at .innerType().shape.props
// but for the props type alias we use the raw inner.
export const TabsProps = TabsNode.innerType().shape.props;
export type TabsPropsType = z.infer<typeof TabsProps>;
