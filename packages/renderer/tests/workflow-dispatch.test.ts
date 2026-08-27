import { describe, it, expect, vi } from "vitest";
import { createWorkflowDispatch } from "../src/client/WorkflowDispatcher";

function okResponse(body: unknown = {}): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}
function errResponse(status: number, body: unknown = {}): Response {
  return { ok: false, status, json: async () => body } as unknown as Response;
}

describe("createWorkflowDispatch", () => {
  it("POSTs to /api/workflows/{name}/execute with {input: args}", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(okResponse());
    const dispatch = createWorkflowDispatch({ fetchImpl });

    await dispatch("createProduct", { name: "Widget", price: 9 });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/workflows/createProduct/execute");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ input: { name: "Widget", price: 9 } });
  });

  it("sends {input: {}} when args omitted", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(okResponse());
    const dispatch = createWorkflowDispatch({ fetchImpl });
    await dispatch("ping");
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({ input: {} });
  });

  it("encodes the workflow name in the URL", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(okResponse());
    const dispatch = createWorkflowDispatch({ fetchImpl });
    await dispatch("Leave Approval");
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/workflows/Leave%20Approval/execute");
  });

  it("calls onSuccess with the result on a 2xx response", async () => {
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse({ status: "completed", id: 7 })),
      onSuccess,
      onError,
    });
    await dispatch("wf");
    expect(onSuccess).toHaveBeenCalledWith("wf", { status: "completed", id: 7 });
    expect(onError).not.toHaveBeenCalled();
  });

  it("calls onError when the response is not ok", async () => {
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(errResponse(500, {})),
      onSuccess,
      onError,
    });
    await dispatch("wf");
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBe("wf");
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("calls onError with the server-provided message when result.error is set", async () => {
    const onError = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse({ error: "not authorized" })),
      onError,
    });
    await dispatch("wf");
    expect(onError).toHaveBeenCalledWith("wf", "not authorized");
  });

  it("calls onError on a 200 response whose body reports status failed", async () => {
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse({ status: "failed" })),
      onSuccess,
      onError,
    });
    await dispatch("wf");
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("calls onError when fetch throws (network failure)", async () => {
    const onError = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockRejectedValue(new Error("offline")),
      onError,
    });
    await dispatch("wf");
    expect(onError).toHaveBeenCalledWith("wf", "offline");
  });

  it("invokes onStart before dispatching", async () => {
    const order: string[] = [];
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn(async () => {
        order.push("fetch");
        return okResponse();
      }),
      onStart: () => order.push("start"),
    });
    await dispatch("wf");
    expect(order).toEqual(["start", "fetch"]);
  });

  it("no-ops on an empty workflow name", async () => {
    const fetchImpl = vi.fn();
    const onStart = vi.fn();
    const dispatch = createWorkflowDispatch({ fetchImpl, onStart });
    await dispatch("");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(onStart).not.toHaveBeenCalled();
  });

  it("does not reject even when the workflow fails (errors routed to onError)", async () => {
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockRejectedValue(new Error("boom")),
      onError: vi.fn(),
    });
    await expect(dispatch("wf")).resolves.toBeUndefined();
  });
});

// ─────────────────────────────────────────────────────────────────
// Spec E Wave 2 Slice 2 — accessibility announcement seam.
//
// The template glue injects an `announce` callback (backed by the
// library's LiveRegion) so every workflow outcome reaches SRs
// automatically. When absent, dispatch stays silent for a11y (the
// app opted out or is running unit tests).
// ─────────────────────────────────────────────────────────────────

describe("createWorkflowDispatch — a11y announce seam", () => {
  it("calls announce(polite) on success with a humanized message", async () => {
    const announce = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse({ id: 1 })),
      announce,
    });
    await dispatch("createProduct");
    expect(announce).toHaveBeenCalledTimes(1);
    const [text, urgency] = announce.mock.calls[0];
    // Message: humanized workflow name + "completed".
    expect(text).toMatch(/create product.*completed/i);
    expect(urgency).toBe("polite");
  });

  it("calls announce(assertive) on failure with the server message", async () => {
    const announce = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse({ error: "not authorized" })),
      announce,
    });
    await dispatch("deleteInvoice");
    expect(announce).toHaveBeenCalledTimes(1);
    const [text, urgency] = announce.mock.calls[0];
    expect(text).toMatch(/delete invoice/i);
    expect(text).toMatch(/not authorized|failed/i);
    expect(urgency).toBe("assertive");
  });

  it("announces network failures as assertive", async () => {
    const announce = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockRejectedValue(new Error("offline")),
      announce,
    });
    await dispatch("wf");
    expect(announce).toHaveBeenCalledWith(
      expect.stringMatching(/offline|failed/i),
      "assertive",
    );
  });

  it("humanizes snake_case and camelCase workflow names", async () => {
    const announce = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse()),
      announce,
    });
    await dispatch("approve_leave_request");
    expect(announce.mock.calls[0][0]).toMatch(/approve leave request/i);

    announce.mockClear();
    await dispatch("SubmitReimbursement");
    expect(announce.mock.calls[0][0]).toMatch(/submit reimbursement/i);
  });

  it("still calls onSuccess/onError alongside announce (composes)", async () => {
    const announce = vi.fn();
    const onSuccess = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse()),
      announce,
      onSuccess,
    });
    await dispatch("wf");
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(announce).toHaveBeenCalledTimes(1);
  });

  it("silent when no announce provided (opt-in, not required)", async () => {
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn().mockResolvedValue(okResponse()),
    });
    await expect(dispatch("wf")).resolves.toBeUndefined();
  });

  it("does not announce on empty-name no-op dispatches", async () => {
    const announce = vi.fn();
    const dispatch = createWorkflowDispatch({
      fetchImpl: vi.fn(),
      announce,
    });
    await dispatch("");
    expect(announce).not.toHaveBeenCalled();
  });
});
