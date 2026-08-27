import { z } from "zod";
import { AccordionNode } from "@tentoroforge/schema";
export const AccordionProps = AccordionNode.shape.props;
export type AccordionPropsType = z.infer<typeof AccordionProps>;
