import { z } from "zod";
import { DataGridNode } from "@tentoroforge/schema";

export const DataGridProps = DataGridNode.shape.props;
export type DataGridPropsType = z.infer<typeof DataGridProps>;
