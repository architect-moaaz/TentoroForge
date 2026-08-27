import { z } from "zod";
import { AvatarNode } from "@tentoroforge/schema";
export const AvatarProps = AvatarNode.shape.props;
export type AvatarPropsType = z.infer<typeof AvatarProps>;
