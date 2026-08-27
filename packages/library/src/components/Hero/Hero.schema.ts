import { z } from "zod";
import { HeroNode } from "@tentoroforge/schema";
export const HeroProps = HeroNode.shape.props;
export type HeroPropsType = z.infer<typeof HeroProps>;
