import { z } from "zod";
import { AppShellNode } from "@tentoroforge/schema";
export const AppShellProps = AppShellNode.shape.props;
export type AppShellPropsType = z.infer<typeof AppShellProps>;
