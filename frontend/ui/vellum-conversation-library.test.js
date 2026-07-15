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

  test("renders a shallow recent-chat hierarchy without replacing Projects", () => {
    expect(html).toContain('<div className="sb-sec">Now');
    expect(html).toContain('<div className="now-subhead">Continue');
    expect(html).toContain('<div className="now-subhead">Today');
    expect(html).toContain('<div className="now-subhead">Needs follow-up');
    expect(html).toContain('<div className="sb-sec">Spaces');
    expect(html).toContain('<div className="sb-sec">Smart views');
    expect(html).toContain("smartById.set('pinned'");
    expect(html).toContain("smartById.set('follow-up'");
    expect(html).toContain("Projects");
    expect(html).toContain("conversationLibrary.spaces");
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
