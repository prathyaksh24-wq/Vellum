import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");
const api = readFileSync(resolve(here, "../../design/Velllum/uploads/api/conversations.js"), "utf8");

describe("conversation library frontend", () => {
  test("exposes organization and message search through the API adapter", () => {
    expect(api).toContain('client.request("/api/conversations/library")');
    expect(api).toContain('client.request("/api/conversations/search?" + params.toString())');
    expect(api).toContain('"/organization"');
    expect(api).toContain('client.request("/api/conversations/organization/rebuild"');
  });

  test("renders utilities first and keeps the organized chat hierarchy", () => {
    expect(html).toContain('<SidebarSection id="now" label="Now"');
    expect(html).toContain('<div className="now-subhead">Continue');
    expect(html).toContain('<div className="now-subhead">Today');
    expect(html).toContain('<div className="now-subhead">Needs follow-up');
    expect(html).toContain('<SidebarSection id="spaces" label="Spaces"');
    expect(html).toContain('<SidebarSection id="smart-views" label="Smart views"');
    expect(html).toContain('<SidebarSection id="projects" label="Projects"');
    expect(html).toContain("smartById.set('pinned'");
    expect(html).toContain("smartById.set('follow-up'");
    expect(html).toContain("conversationLibrary.spaces");

    const searchIndex = html.indexOf('>Search chats<span');
    const toolsIndex = html.indexOf('<div className="sb-tools">', searchIndex);
    const nowIndex = html.indexOf('<SidebarSection id="now"', toolsIndex);
    const spacesIndex = html.indexOf('<SidebarSection id="spaces"', nowIndex);
    const smartIndex = html.indexOf('<SidebarSection id="smart-views"', spacesIndex);
    const projectsIndex = html.indexOf('<SidebarSection id="projects"', smartIndex);
    expect([searchIndex, toolsIndex, nowIndex, spacesIndex, smartIndex, projectsIndex].every((index) => index >= 0)).toBe(true);
    expect(searchIndex).toBeLessThan(toolsIndex);
    expect(toolsIndex).toBeLessThan(nowIndex);
    expect(nowIndex).toBeLessThan(spacesIndex);
    expect(spacesIndex).toBeLessThan(smartIndex);
    expect(smartIndex).toBeLessThan(projectsIndex);
  });

  test("uses accessible animated collapsible sections with persisted state", () => {
    expect(html).toContain("const SidebarSection = ({id, label, count, open, onToggle, children})");
    expect(html).toContain('aria-expanded={open} aria-controls={regionId}');
    expect(html).toContain(".sb-section-collapse{display:grid;grid-template-rows:0fr");
    expect(html).toContain(".sb-section-collapse.open{grid-template-rows:1fr");
    expect(html).toContain("{now: true, spaces: true, smartViews: true, projects: true}");
    expect(html).toContain("'vellum-sidebar-sections'");
  });

  test("searches message content and jumps to the matching message", () => {
    expect(html).toContain("API.conversations.search(q, filters)");
    expect(html).toContain("hits[0].message_id");
    expect(html).toContain("document.getElementById('m-' + messageId)?.scrollIntoView");
    expect(html).toContain("Search titles and messages");
  });

  test("supports durable manual Space corrections and automatic reset", () => {
    expect(html).toContain("const SpacePickerModal");
    expect(html).toContain("API.conversations.organize(id, patch)");
    expect(html).toContain("assignment: 'manual'");
    expect(html).toContain("assignment: 'automatic'");
  });
});
