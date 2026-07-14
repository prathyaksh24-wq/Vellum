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
    expect(html).toContain("SKILL_ORIGINS");
    expect(html).toContain("Built into Vellum");
    expect(html).toContain("Learned by you");
    expect(html).toContain("Learned by Vellum");
  });

  test("exposes lifecycle, accessibility, provenance, and raw SKILL.md surfaces", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    for (const label of ["Installed", "Discover", "Pending", "Duplicate Review", "Archived", "SKILL.md", "Install CLI", "Prompt", "Recent scrubbed tasks", "Security findings", "Support files"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("prefers-reduced-motion");
    expect(html).toContain("repository_url");
    expect(html).toContain("source_ref");
    expect(html).toContain('<VSelect className="sk-filter"');
    expect(html).toContain('className="sk-source-modal"');
    expect(html).not.toContain('>Rendered</button>');
    expect(html).not.toContain("sub:'Install by URL'");
    expect(html).not.toContain("value:'well-known'");
    expect(html).toContain("if(source!=='all')searchBody.source=source");
  });

  test("uses a non-blocking learn state machine tied to pending approval", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    for (const status of ["LEARNING", "LEARNT", "DRAFT_APPROVED", "AWAITING_USER_APPROVAL", "INSTALLING", "INSTALLED"]) {
      expect(html).toContain(status);
    }
    expect(html).toContain('className="sk-learn-feed"');
    expect(html).toContain("setLearnOpen(false);setLearnSource('');setLearnError('');startLearnActivity(sourceValue)");
    expect(html).toContain("SKILL_ACTIVITY_STORAGE");
    expect(html).toContain("skillActivityListeners");
    expect(html).toContain("skNoteStage");
    expect(html).toContain("sk-learn-note.leaving");
  });

  test("renders ranked discovery, resilient details, validation, and direct uninstall confirmation", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    for (const label of ["Most Popular", "Trending", "Most Downloaded", "Retry inspection", "Confirm skill removal", "Remove skill"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("isValidSkillLearnInput");
    expect(html).toContain("valid public skill URL");
    expect(html).toContain("confirm:true");
    expect(html).toContain("Built-in skills can't be removed");
    expect(html).toContain("startInstallActivity(payload)");
    expect(html).toContain("SKILL_RANKING_OPTIONS");
    expect(html).toContain('ariaLabel="Discovery ranking"');
    expect(html).toContain("setInterval(()=>loadList(false,''),300000)");
    expect(html).toContain("item.author?` · by ${item.author}`:''");
  });

  test("colocated API client supports cancellable typed operations", () => {
    const api = fs.readFileSync(apiPath, "utf8");
    expect(api).toContain("skillsOverview");
    expect(api).toContain("skillsCatalog");
    expect(api).toContain("pendingApprove");
    expect(api).toContain("duplicateDecision");
    expect(api).toContain("hubMutation");
    expect(api).toContain('client.request("/api/skills/learn"');
    expect(api).not.toContain("learnExecute");
    expect(api).toContain("signal: signal");
  });
});
