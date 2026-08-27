import { z } from "zod";

const SchematicMarker = z.object({
  id:     z.string().optional(),
  x:      z.number(),
  y:      z.number(),
  label:  z.string().optional(),
  status: z.string().optional(),          // resolved via statusColors
  color:  z.string().optional(),          // explicit override
  shape:  z.enum(["circle", "square", "pin"]).optional(),
});

const SchematicRegion = z.object({
  id:     z.string().optional(),
  label:  z.string().optional(),
  x:      z.number().optional(),
  y:      z.number().optional(),
  w:      z.number().optional(),
  h:      z.number().optional(),
  points: z.array(z.array(z.number())).optional(),  // polygon [[x,y],...]
  color:  z.string().optional(),
});

export const SchematicProps = z.object({
  // Coordinate space the markers/regions are expressed in.
  width:   z.number().optional(),   // default 100
  height:  z.number().optional(),   // default 60
  grid:    z.object({ cols: z.number(), rows: z.number() }).optional(),
  regions: z.array(SchematicRegion).optional(),
  markers: z.preprocess((v) => (v == null ? [] : v),
    z.union([z.array(SchematicMarker), z.string().min(1)])),  // array or binding
  statusColors: z.record(z.string()).optional(),   // status → color
  showLabels:   z.boolean().optional(),
  heightPx:     z.number().optional(),  // rendered height, default 320
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SchematicPropsType = z.infer<typeof SchematicProps>;
