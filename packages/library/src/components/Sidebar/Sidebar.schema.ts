import { z } from "zod";
import { SidebarNode } from "@tentoroforge/schema";
export const SidebarProps = SidebarNode.shape.props;
export type SidebarPropsType = z.infer<typeof SidebarProps>;
