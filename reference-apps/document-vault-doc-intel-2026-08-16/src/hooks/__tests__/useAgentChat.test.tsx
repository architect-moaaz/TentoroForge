/**
 * Tests for useAgentChat. Runs under vitest + jsdom.
 *
 * NOTE: the app-foundation template does not currently ship a vitest
 * config — this file lives alongside the hook so a future test-runner
 * setup will pick it up. It intentionally has no template placeholders
 * so it stays inert until then.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { useAgentChat } from "../useAgentChat";

function wrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

function mockFetchResponse(body: unknown, init: { status?: number } = {}) {
  return {
    ok: (init.status ?? 200) < 400,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

describe("useAgentChat", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    // @ts-expect-error — jsdom-friendly global stub
    global.fetch = fetchSpy;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts to /api/agent/chat with the correct body", async () => {
    fetchSpy.mockResolvedValueOnce(
      mockFetchResponse({ message: "ok", data: { matches: [] } })
    );

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    await act(async () => {
      await result.current.send({
        message: "Identify this product",
        attachments: ["file_abc123"],
      });
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/agent/chat");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({
      message: "Identify this product",
      attachments: ["file_abc123"],
    });
  });

  it("defaults attachments to [] when omitted", async () => {
    fetchSpy.mockResolvedValueOnce(mockFetchResponse({ message: "hi" }));

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    await act(async () => {
      await result.current.send({ message: "hi" });
    });

    const [, init] = fetchSpy.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ message: "hi", attachments: [] });
  });

  it("toggles isLoading during flight and clears after", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    fetchSpy.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    expect(result.current.isLoading).toBe(false);

    let sendPromise: Promise<unknown> = Promise.resolve();
    act(() => {
      sendPromise = result.current.send({ message: "go" });
    });

    await waitFor(() => expect(result.current.isLoading).toBe(true));

    await act(async () => {
      resolveFetch(mockFetchResponse({ message: "done" }));
      await sendPromise;
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it("populates lastReply on success (message + data + toolCalls)", async () => {
    fetchSpy.mockResolvedValueOnce(
      mockFetchResponse({
        message: "Here are the matches",
        data: { matches: [{ id: "p1", title: "Blue shoe" }] },
        toolCalls: [{ tool: "firecrawl_search", ok: true }],
      })
    );

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    await act(async () => {
      await result.current.send({ message: "match", attachments: ["f1"] });
    });

    expect(result.current.lastReply).not.toBeNull();
    expect(result.current.lastReply?.message).toBe("Here are the matches");
    expect(result.current.lastReply?.data).toEqual({
      matches: [{ id: "p1", title: "Blue shoe" }],
    });
    expect(result.current.lastReply?.toolCalls).toEqual([
      { tool: "firecrawl_search", ok: true },
    ]);
  });

  it("surfaces the server's error message on non-200", async () => {
    fetchSpy.mockResolvedValueOnce(
      mockFetchResponse(
        { error: { message: "Vision API is down" } },
        { status: 500 }
      )
    );

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    await expect(
      act(async () => {
        await result.current.send({ message: "identify" });
      })
    ).rejects.toThrow("Vision API is down");

    await waitFor(() =>
      expect(result.current.error?.message).toBe("Vision API is down")
    );
  });

  it("maps 404 to a helpful 'no agent configured' message when the server sends none", async () => {
    fetchSpy.mockResolvedValueOnce(mockFetchResponse({}, { status: 404 }));

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    await expect(
      act(async () => {
        await result.current.send({ message: "x" });
      })
    ).rejects.toThrow(/no agent is configured/i);
  });

  it("maps 429 to a rate-limit message", async () => {
    fetchSpy.mockResolvedValueOnce(mockFetchResponse({}, { status: 429 }));

    const { result } = renderHook(() => useAgentChat(), { wrapper: wrapper() });

    await expect(
      act(async () => {
        await result.current.send({ message: "x" });
      })
    ).rejects.toThrow(/rate limit/i);
  });
});
