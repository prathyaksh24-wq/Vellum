import { beforeEach, describe, expect, test, vi } from "vitest";

async function runtime() {
  vi.resetModules();
  window.VellumUI = {};
  await import("../../design/Velllum/uploads/components/observability-action-runtime.js");
  return window.VellumUI.ObservabilityActions;
}

function receipt(result, status = "applied") {
  return {
    action_id: "observability.stream.set",
    status,
    result,
  };
}

describe("Observability App Action adapter", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("repeated pause and resume receipts are idempotent", async () => {
    const actions = await runtime();
    const pause = receipt({observability_control_patch:{version:1,streaming:false,reconnect:false}});
    const resume = receipt({observability_control_patch:{version:1,streaming:true,reconnect:false}});

    const paused = actions.applyReceipt(actions.initialState(), pause);
    const pausedAgain = actions.applyReceipt(paused, pause);
    const resumed = actions.applyReceipt(pausedAgain, resume);
    const resumedAgain = actions.applyReceipt(resumed, resume);

    expect(pausedAgain).toEqual(paused);
    expect(resumedAgain).toEqual(resumed);
    expect(resumed.streaming).toBe(true);
  });

  test("reconnect advances only the local EventSource revision", async () => {
    const actions = await runtime();
    const reconnect = receipt({observability_control_patch:{version:1,streaming:true,reconnect:true}});

    const first = actions.applyReceipt(actions.initialState(), reconnect);
    const second = actions.applyReceipt(first, reconnect);

    expect(first.reconnectRevision).toBe(1);
    expect(second.reconnectRevision).toBe(2);
    expect(second.streaming).toBe(true);
  });

  test("refresh receipts replace the visible operational snapshot", async () => {
    const actions = await runtime();
    const snapshot = {period:"7d",usage:{total_tokens:42},runs:{active:0}};

    const refreshed = actions.applyReceipt(
      actions.initialState(),
      receipt({changed:false,observability_snapshot:snapshot}),
    );
    const failed = actions.applyReceipt(refreshed, receipt({}, "failed"));

    expect(refreshed.snapshot).toEqual(snapshot);
    expect(failed).toEqual(refreshed);
  });

  test("rejects malformed control patches", async () => {
    const actions = await runtime();

    expect(() => actions.applyReceipt(
      actions.initialState(),
      receipt({observability_control_patch:{version:2,streaming:false}}),
    )).toThrow("INVALID_OBSERVABILITY_CONTROL_PATCH");
  });
});
