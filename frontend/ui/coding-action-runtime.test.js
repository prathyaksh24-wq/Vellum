import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadRuntime() {
  vi.resetModules();
  window.VellumUI = {};
  await import("../../design/Velllum/uploads/components/coding-action-runtime.js");
  return window.VellumUI.CodingActions;
}

function receipt(actionId, navigation, status = "applied") {
  return { action_id: actionId, status, result: navigation ? { navigation } : {} };
}

describe("coding action receipt runtime", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("routes coding and GitHub receipts through one navigation seam", async () => {
    const actions = await loadRuntime();
    const navigations = [];
    const runtime = actions.createRuntime({
      navigate: (navigation, actionReceipt) => navigations.push({ navigation, actionId: actionReceipt.action_id }),
    });

    expect(runtime.applyReceipt(receipt("coding.workspace.open", { kind: "coding_workspace", url: "vellum-workspace.html?session=one" }))).toBe(true);
    expect(runtime.applyReceipt(receipt("github.pull_request.open", { kind: "external", url: "https://github.com/acme/repo/pull/7" }))).toBe(true);
    expect(runtime.applyReceipt(receipt("github.pull_request.create", { kind: "external", url: "https://github.com/acme/repo/pull/8" }))).toBe(true);
    expect(navigations).toHaveLength(3);
  });

  test("ignores confirmation, failure, and unrelated receipts", async () => {
    const actions = await loadRuntime();
    const navigate = vi.fn();
    const runtime = actions.createRuntime({ navigate });

    expect(runtime.applyReceipt(receipt("github.pull_request.create", null, "confirmation_required"))).toBe(false);
    expect(runtime.applyReceipt(receipt("github.pull_request.open", { url: "https://example.com" }, "failed"))).toBe(false);
    expect(runtime.applyReceipt(receipt("conversation.open", { url: "elsewhere" }))).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });
});
