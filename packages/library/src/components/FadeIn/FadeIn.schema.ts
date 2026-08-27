import { z } from "zod";
import { FadeInNode } from "@tentoroforge/schema";
export const FadeInProps = FadeInNode.shape.props;
export type FadeInPropsType = z.infer<typeof FadeInProps>;
