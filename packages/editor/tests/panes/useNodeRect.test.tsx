import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { useNodeRect } from "../../src/panes/Canvas/useNodeRect";

function Probe({ id, onRect }: any) {
  const rect = useNodeRect(id);
  React.useEffect(() => { onRect(rect); }, [rect, onRect]);
  return <div data-node-id={id} style={{ width: 100, height: 50 }}>x</div>;
}

describe("useNodeRect", () => {
  it("returns null when id is null", () => {
    let received: any = "unset";
    render(<Probe id={null} onRect={(r: any) => { received = r; }} />);
    expect(received).toBeNull();
  });

  it("returns a rect-like object when element with data-node-id exists", () => {
    let received: any = "unset";
    render(<Probe id="x" onRect={(r: any) => { received = r; }} />);
    // jsdom returns 0s for layout; just confirm shape
    expect(received).toMatchObject({ top: expect.any(Number), left: expect.any(Number), width: expect.any(Number), height: expect.any(Number) });
  });
});
