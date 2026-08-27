import { z } from "zod";
import { FilterBarNode } from "@tentoroforge/schema";
export const FilterBarProps = FilterBarNode.shape.props;
export type FilterBarPropsType = z.infer<typeof FilterBarProps>;
