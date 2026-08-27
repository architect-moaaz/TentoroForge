import { z } from "zod";
import { InspectorPanelNode } from "@tentoroforge/schema";
export const InspectorPanelProps = InspectorPanelNode.shape.props;
export type InspectorPanelPropsType = z.infer<typeof InspectorPanelProps>;
