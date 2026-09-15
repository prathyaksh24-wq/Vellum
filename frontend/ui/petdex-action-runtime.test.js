import { beforeEach, describe, expect, test, vi } from "vitest";

async function runtime() {
  vi.resetModules();
  window.VellumUI = {};
  await import("../../design/Velllum/uploads/components/petdex-action-runtime.js");
  return window.VellumUI.PetdexActions;
}

describe("Petdex App Action runtime", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("applies a versioned receipt and preserves gallery availability", async () => {
    const subject = await runtime();
    const current = {
      revision: 2,
      installed: ["boba"],
      available: ["boba", "zoro"],
      active: "boba",
      hidden: false,
      size: "md",
      position: {},
    };
    const receipt = {
      status: "applied",
      result: {
        petdex_patch: {
          version: 1,
          base_revision: 2,
          revision: 3,
          state: {...current, installed: ["boba", "zoro"], active: "zoro"},
        },
      },
    };

    expect(subject.applyReceipt(current, receipt)).toMatchObject({
      revision: 3,
      installed: ["boba", "zoro"],
      available: ["boba", "zoro"],
      active: "zoro",
    });
  });

  test("rejects stale mutations instead of overwriting newer device state", async () => {
    const subject = await runtime();
    const current = {revision: 4, installed: ["boba"], active: "boba", hidden: false, size: "md", position: {}};
    const receipt = {
      status: "applied",
      result: {petdex_patch: {version: 1, base_revision: 2, revision: 3, state: {...current, revision: 3, hidden: true}}},
    };

    expect(() => subject.applyReceipt(current, receipt)).toThrow("STALE_PETDEX_RECEIPT");
  });

  test("maps named corners without storing viewport-specific coordinates", async () => {
    const subject = await runtime();

    expect(subject.positionStyle({anchor: "bottom-left"}, {width: 1200, height: 800})).toEqual({left: 20, top: 550});
    expect(subject.positionStyle({x: 45, y: 70}, {width: 1200, height: 800})).toEqual({left: 45, top: 70});
  });
});
