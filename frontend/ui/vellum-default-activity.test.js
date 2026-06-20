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
  });
});
