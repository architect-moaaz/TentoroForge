import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider, useToast } from "../../src/chrome/Toaster";

function TestPushButton({ title, kind }: { title: string; kind?: "info" | "error" }) {
  const { push } = useToast();
  return <button onClick={() => push({ title, kind })}>Push Toast</button>;
}

describe("Toaster", () => {
  it("shows a toast when pushed", async () => {
    render(
      <ToastProvider>
        <TestPushButton title="Hello Toast" kind="info" />
      </ToastProvider>
    );
    await userEvent.click(screen.getByRole("button", { name: /push toast/i }));
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Hello Toast")).toBeInTheDocument();
  });

  it("auto-dismisses toast after 5 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    render(
      <ToastProvider>
        <TestPushButton title="Auto-dismiss" kind="error" />
      </ToastProvider>
    );
    await user.click(screen.getByRole("button", { name: /push toast/i }));
    expect(screen.getByText("Auto-dismiss")).toBeInTheDocument();
    // Advance fake timers past 5s auto-dismiss
    await act(async () => { vi.advanceTimersByTime(5100); });
    expect(screen.queryByText("Auto-dismiss")).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});
