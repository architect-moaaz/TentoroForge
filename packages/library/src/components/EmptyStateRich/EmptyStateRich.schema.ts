import { z } from "zod";
import { EmptyStateRichNode } from "@tentoroforge/schema";
export const EmptyStateRichProps = EmptyStateRichNode.shape.props;
export type EmptyStateRichPropsType = z.infer<typeof EmptyStateRichProps>;
