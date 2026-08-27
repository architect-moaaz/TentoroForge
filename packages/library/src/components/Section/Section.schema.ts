import { z } from "zod";
import { SectionNode } from "@tentoroforge/schema";
export const SectionProps = SectionNode.shape.props;
export type SectionPropsType = z.infer<typeof SectionProps>;
