import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";

const htmlPath = path.resolve("../design/Velllum/uploads/Vellum Default Re-designed.html");
const apiPath = path.resolve("../design/Velllum/uploads/api/plugins.js");

describe("production Skills Hub", () => {
  test("uses live catalog contracts without a runtime seed catalog", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    expect(html).toContain("const SkillsHubView");
    expect(html).toContain("<SkillsHubView/>");
    expect(html).not.toContain("useState(SEED_SKILLS)");
    expect(html).not.toContain("const SEED_SKILLS");
    expect(html).toContain("API.plugins.skillsCatalog");
    expect(html).toContain("API.plugins.hubSearch");
  });

  test("exposes lifecycle, accessibility, provenance, and raw SKILL.md surfaces", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    for (const label of ["Installed", "Discover", "Pending", "Duplicate Review", "Archived", "SKILL.md", "Recent scrubbed tasks", "Security findings", "Support files"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("prefers-reduced-motion");
    expect(html).toContain("repository_url");
    expect(html).toContain("source_ref");
  });

  test("colocated API client supports cancellable typed operations", () => {
    const api = fs.readFileSync(apiPath, "utf8");
    expect(api).toContain("skillsOverview");
    expect(api).toContain("skillsCatalog");
    expect(api).toContain("pendingApprove");
    expect(api).toContain("duplicateDecision");
    expect(api).toContain("hubMutation");
    expect(api).toContain("signal: signal");
  });
});
