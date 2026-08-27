import { z } from "zod";
import { CommandPaletteNode } from "@tentoroforge/schema";
export const CommandPaletteProps = CommandPaletteNode.shape.props;
export type CommandPalettePropsType = z.infer<typeof CommandPaletteProps>;
