import { z } from "zod";

export const SlotNode = z
  .object({
    id: z.string().min(1),
    type: z.literal("Slot"),
    props: z.object({ name: z.string().min(1) }).strict(),
  })
  .strict();

export type SlotNode = z.infer<typeof SlotNode>;
