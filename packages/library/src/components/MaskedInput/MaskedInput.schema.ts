import { z } from "zod";

/** Apply a mask where `#` consumes a digit and any other char is an inserted literal. */
export function applyMask(value: string, mask: string): string {
  const digits = (value ?? "").replace(/\D/g, "");
  let out = "";
  let di = 0;
  for (const m of mask) {
    if (di >= digits.length) break;
    if (m === "#") out += digits[di++];
    else out += m;
  }
  return out;
}

export const MaskedInputProps = z.object({
  name:        z.string().default("masked"),
  label:       z.string().optional(),
  mask:        z.string().default("###"),
  placeholder: z.string().optional(),
  disabled:    z.boolean().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type MaskedInputPropsType = z.infer<typeof MaskedInputProps>;
