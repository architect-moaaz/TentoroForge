import { z } from "zod";
import { ApprovalStepperNode } from "@tentoroforge/schema";
export const ApprovalStepperProps = ApprovalStepperNode.shape.props;
export type ApprovalStepperPropsType = z.infer<typeof ApprovalStepperProps>;
