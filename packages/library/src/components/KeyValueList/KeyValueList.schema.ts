import { z } from "zod";
import { KeyValueListNode } from "@tentoroforge/schema";
export const KeyValueListProps = KeyValueListNode.shape.props;
export type KeyValueListPropsType = z.infer<typeof KeyValueListProps>;
