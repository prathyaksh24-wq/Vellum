import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadPluginsApi(fetchImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request: async (path, options) => fetchImpl(path, options),
      jsonOptions: (method, body) => ({ method, body }),
    },
  };
  await import("../../../design/Velllum/uploads/api/plugins.js");
  return window.VellumApi.plugins;
}

describe("Vellum plugins API adapter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("reads backend capability discovery through a stable adapter method", async () => {
    const fetchImpl = vi.fn(async (path) => {
      expect(path).toBe("/api/capabilities");
      return {
        api_version: "v1",
        features: {
          spotify: { enabled: true, contract: "v1", endpoints: { status: "/api/plugins/spotify/status" } },
        },
      };
    });
    const api = await loadPluginsApi(fetchImpl);

    await expect(api.capabilities()).resolves.toMatchObject({
      api_version: "v1",
      features: {
        spotify: { enabled: true },
      },
    });
  });

  test("owns the YouTube OAuth and synchronization contract", async () => {
    const fetchImpl = vi.fn(async (path, options) => ({ path, options }));
    const api = await loadPluginsApi(fetchImpl);

    await api.youtubeStatus();
    await api.youtubeIntelligenceStatus();
    await api.youtubeOAuthStart();
    await api.youtubeSync("snapshot-1");
    await api.youtubeDisconnect();

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/plugins/youtube/status");
    expect(fetchImpl.mock.calls[1][0]).toBe("/api/plugins/youtube/intelligence/status");
    expect(fetchImpl.mock.calls[2][0]).toBe("/api/plugins/youtube/oauth/start");
    expect(fetchImpl.mock.calls[3][0]).toBe("/api/plugins/youtube/sync");
    expect(fetchImpl.mock.calls[4]).toEqual([
      "/api/plugins/youtube/connection",
      { method: "DELETE" },
    ]);
  });

  test("owns scoped Discord bot reads and sends", async () => {
    const fetchImpl = vi.fn(async (path, options) => ({ path, options }));
    const api = await loadPluginsApi(fetchImpl);

    await api.discordStatus();
    await api.discordInstall();
    await api.discordGuilds();
    await api.discordChannels("guild-1");
    await api.discordMessages("channel-1", 10);
    await api.discordSend("channel-1", "Hello", true);
    await api.discordReply("channel-1", "message-1", "Reply", true);
    await api.discordEditOwn("channel-1", "message-1", "Edited", true);
    await api.discordDeleteOwn("channel-1", "message-1", true);
    await api.discordReact("channel-1", "message-1", "thumbsup:1", true);
    await api.discordCreateThread("channel-1", "message-1", "Thread", true);
    await api.discordSendThread("channel-1", "thread-1", "Thread reply", true);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    await api.discordSendAttachment("channel-1", file, "Evidence", true);

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/plugins/discord/status");
    expect(fetchImpl.mock.calls[1][0]).toBe("/api/plugins/discord/install");
    expect(fetchImpl.mock.calls[2][0]).toBe("/api/plugins/discord/guilds");
    expect(fetchImpl.mock.calls[3][0]).toBe("/api/plugins/discord/guilds/guild-1/channels");
    expect(fetchImpl.mock.calls[4][0]).toBe("/api/plugins/discord/channels/channel-1/messages?limit=10");
    expect(fetchImpl.mock.calls[5]).toEqual([
      "/api/plugins/discord/channels/channel-1/messages",
      { method: "POST", body: { content: "Hello", confirm: true } },
    ]);
    expect(fetchImpl.mock.calls[6][0]).toBe("/api/plugins/discord/channels/channel-1/messages/message-1/reply");
    expect(fetchImpl.mock.calls[7][0]).toBe("/api/plugins/discord/channels/channel-1/messages/message-1");
    expect(fetchImpl.mock.calls[8][0]).toBe("/api/plugins/discord/channels/channel-1/messages/message-1/delete");
    expect(fetchImpl.mock.calls[9][0]).toBe("/api/plugins/discord/channels/channel-1/messages/message-1/reactions");
    expect(fetchImpl.mock.calls[10][0]).toBe("/api/plugins/discord/channels/channel-1/messages/message-1/threads");
    expect(fetchImpl.mock.calls[11][0]).toBe("/api/plugins/discord/channels/channel-1/threads/thread-1/messages");
    expect(fetchImpl.mock.calls[12][0]).toBe("/api/plugins/discord/channels/channel-1/attachments");
    expect(fetchImpl.mock.calls[12][1].method).toBe("POST");
    expect(fetchImpl.mock.calls[12][1].body).toBeInstanceOf(FormData);
  });
});
