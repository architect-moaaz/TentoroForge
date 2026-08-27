import { describe, it, expect } from "vitest";
import { createRegistry } from "../src/registry";
import { Button } from "../src/components/Button/Button";
import { ButtonProps } from "../src/components/Button/Button.schema";

describe("Registry remap — Button.icon aliases", () => {
  it("accepts iconName as an alias for icon", () => {
    const r = createRegistry();
    r.register({ name: "Button", component: Button, propsSchema: ButtonProps, category: "interactive", acceptsChildren: false });
    const props = r.validateProps("Button", { label: "Add", iconName: "plus" });
    expect((props as any).icon).toBe("plus");
    expect((props as any).iconName).toBeUndefined();
  });
});
