import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegenerateModal } from "../../src/panes/AI/RegenerateModal";

describe("RegenerateModal validation", () => {
  it("disables Accept when proposed subtree is invalid", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      subtree: { type: "Box" },  // missing required id → invalid Node
    }), { status: 200 })));

    render(<RegenerateModal open={true} onClose={() => {}} subtree={{ id: "x", type: "Box" }} onAccept={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/describe what you want/i), "make it modern");
    await userEvent.click(screen.getByRole("button", { name: /regenerate/i }));
    await waitFor(() => screen.getByText(/invalid|error/i));
    expect(screen.getByRole("button", { name: /accept/i })).toBeDisabled();
  });

  it("enables Accept when proposed subtree is valid Node", async () => {
    const valid = { id: "n1", type: "Box", children: [] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ subtree: valid }), { status: 200 })));

    render(<RegenerateModal open={true} onClose={() => {}} subtree={{ id: "x", type: "Box" }} onAccept={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/describe what you want/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /regenerate/i }));
    await waitFor(() => screen.getByRole("button", { name: /accept/i }));
    expect(screen.getByRole("button", { name: /accept/i })).not.toBeDisabled();
  });

  it("renders Before/After side-by-side", async () => {
    const valid = { id: "n1", type: "Box", children: [] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ subtree: valid }), { status: 200 })));

    render(<RegenerateModal open={true} onClose={() => {}} subtree={{ id: "x", type: "Box" }} onAccept={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/describe what you want/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /regenerate/i }));
    await waitFor(() => screen.getByText("Before"));
    expect(screen.getByText("Before")).toBeInTheDocument();
    expect(screen.getByText("After")).toBeInTheDocument();
  });
});
