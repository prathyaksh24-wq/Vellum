import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";

const htmlPath = path.resolve("../design/Velllum/uploads/Vellum Default Re-designed.html");

describe("Vellum default activity status", () => {
  test("rotates thinking copy in the visible activity row while waiting", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("THINKING_ROTATION_LABELS");
    expect(html).toContain("isThinkingActivity");
    expect(html).toContain("setInterval(() => setThinkingIndex");
    expect(html).toContain("clearInterval(id)");
    expect(html).toContain("Cooking up your answer");
    expect(html).toContain("typingLabel");
    expect(html).toContain("typingText");
  });

  test("composer exposes stop answering control and abort plumbing", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("onStop");
    expect(html).toContain("stopActiveTurn");
    expect(html).toContain("controller.abort()");
    expect(html).toContain("title=\"Stop answering\"");
    expect(html).toContain("IcStop");
  });

  test("chat row menu uses a viewport clamped position helper", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("clampMenuPosition");
    expect(html).toContain("Math.max(12");
    expect(html).toContain("Math.min(x");
    expect(html).toContain("clampMenuPosition(pos, 230, 260)");
  });
});
