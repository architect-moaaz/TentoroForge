import { z } from "zod";
import { ClusterNode } from "@tentoroforge/schema";
export const ClusterProps = ClusterNode.shape.props;
export type ClusterPropsType = z.infer<typeof ClusterProps>;
