import { z } from "zod";
import { PersonCardNode } from "@tentoroforge/schema";
export const PersonCardProps = PersonCardNode.shape.props;
export type PersonCardPropsType = z.infer<typeof PersonCardProps>;
