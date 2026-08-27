import { z } from "zod";

const Slide = z.object({
  image:   z.string().optional(),
  title:   z.string().optional(),
  caption: z.string().optional(),
});

export const CarouselProps = z.object({
  items:     z.array(Slide).default([]),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});

export type CarouselPropsType = z.infer<typeof CarouselProps>;
