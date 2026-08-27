import { z } from "zod";
import { StaggerNode } from "@tentoroforge/schema";
export const StaggerProps = StaggerNode.shape.props;
export type StaggerPropsType = z.infer<typeof StaggerProps>;
