import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadCatalog() {
  vi.resetModules();
  window.VellumUI = {};
  await import("../../design/Velllum/uploads/components/agent-catalog.js");
  return window.VellumUI.AgentCatalog;
}

describe("Agent catalog projection", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("uses the built-in presentation list until runtime discovery completes", async () => {
    const catalog = await loadCatalog();
    const builtins = [{id: "youtube", name: "YouTube Agent"}];

    expect(catalog.merge(builtins, null)).toEqual(builtins);
  });

  test("projects every available runtime sub-agent and preserves known presentation metadata", async () => {
    const catalog = await loadCatalog();
    const youtubeIcon = () => null;
    const fallbackIcon = () => null;
    const result = catalog.merge(
      [{id: "youtube", name: "YouTube Agent", icon: youtubeIcon, tag: "Videos"}],
      [
        {id: "youtube", name: "YoutubeAgent", enabled: true, status: "available"},
        {id: "calendar", name: "CalendarAgent", description: "Private schedule operations.", enabled: true, status: "available"},
        {id: "x", name: "XAgent", enabled: false, status: "unavailable"},
      ],
      {fallbackIcon},
    );

    expect(result.map(agent => agent.id)).toEqual(["youtube", "calendar"]);
    expect(result[0]).toMatchObject({name: "YouTube Agent", icon: youtubeIcon, tag: "Videos"});
    expect(result[1]).toMatchObject({
      id: "calendar",
      profileId: "CalendarAgent",
      name: "Calendar Agent",
      icon: fallbackIcon,
      tag: "Private schedule operations.",
    });
  });

  test("normalizes future multi-word profile IDs without a fixed alias", async () => {
    const catalog = await loadCatalog();

    expect(catalog.clientId("MarketResearchAgent")).toBe("marketresearch");
    expect(catalog.displayName("MarketResearchAgent")).toBe("Market Research Agent");
  });
});
