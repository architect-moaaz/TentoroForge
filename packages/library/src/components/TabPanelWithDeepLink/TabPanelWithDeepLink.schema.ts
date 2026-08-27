import { z } from "zod";
import { TabPanelWithDeepLinkNode } from "@tentoroforge/schema";
export const TabPanelWithDeepLinkProps = TabPanelWithDeepLinkNode.shape.props;
export type TabPanelWithDeepLinkPropsType = z.infer<typeof TabPanelWithDeepLinkProps>;
