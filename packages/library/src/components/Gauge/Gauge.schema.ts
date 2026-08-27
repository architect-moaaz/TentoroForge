import { z } from "zod";

export const GaugeThreshold = z.object({
  value: z.number(),               // upper bound of this zone (in value units)
  color: z.string(),               // CSS color or token
  label: z.string().optional(),
});

export const GaugeProps = z.object({
  value:      z.number().default(0),
  min:        z.number().default(0),
  max:        z.number().default(100),
  label:      z.string().optional(),
  unit:       z.string().optional(),           // e.g. "%", "°C", "rpm"
  thresholds: z.array(GaugeThreshold).optional(),  // zone bands, ascending by value
  size:       z.number().optional(),           // px, default 180
  showValue:  z.boolean().optional(),          // default true
  bind:       z.string().optional(),
  className:  z.string().optional(),
  style:      z.record(z.unknown()).optional(),
});
export type GaugePropsType = z.infer<typeof GaugeProps>;
