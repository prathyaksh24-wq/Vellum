(function () {
  var client = window.VellumApi.client;
  window.VellumApi.plugins = {
    list: function () { return client.request("/api/plugins"); },
    setEnabled: function (id, enabled) { return client.request("/api/plugins/" + encodeURIComponent(id) + "/state", client.jsonOptions("POST", {enabled:!!enabled})); },
    skills: function () { return client.request("/api/skills"); },
    skillsOverview: function (signal) { return client.request("/api/skills/v2/overview", { signal: signal }); },
    skillsCatalog: function (params, signal) {
      var query = new URLSearchParams(params || {}).toString();
      return client.request("/api/skills/v2/catalog" + (query ? "?" + query : ""), { signal: signal });
    },
    skillDetail: function (name, signal) { return client.request("/api/skills/" + encodeURIComponent(name), { signal: signal }); },
    skillAction: function (body, signal) { return client.request("/api/skills/action", client.jsonOptions("POST", body, signal)); },
    pendingApprove: function (id) { return client.request("/api/skills/v2/pending/" + encodeURIComponent(id) + "/approve", client.jsonOptions("POST")); },
    pendingReject: function (id) { return client.request("/api/skills/v2/pending/" + encodeURIComponent(id) + "/reject", client.jsonOptions("POST")); },
    duplicateDecision: function (id, decision, reason) { return client.request("/api/skills/v2/duplicates/" + encodeURIComponent(id) + "/decision", client.jsonOptions("POST", {decision:decision, reason:reason || ""})); },
    hubSearch: function (body, signal) { return client.request("/api/skills/v2/hub/search", client.jsonOptions("POST", body, signal)); },
    hubInspect: function (identifier, signal) { return client.request("/api/skills/v2/hub/inspect", client.jsonOptions("POST", {identifier:identifier}, signal)); },
    hubMutation: function (action, body) { return client.request("/api/skills/v2/hub/" + action, client.jsonOptions("POST", body)); },
    learn: function (source, threadId, category) { return client.request("/api/skills/learn", client.jsonOptions("POST", {source:source, thread_id:threadId || "skills-hub", category:category || "community"})); },
    capabilities: function () { return client.request("/api/capabilities"); },
    youtubeStatus: function () { return client.request("/api/plugins/youtube/status"); },
    youtubeIntelligenceStatus: function () { return client.request("/api/plugins/youtube/intelligence/status"); },
    youtubeOAuthStart: function () { return client.request("/api/plugins/youtube/oauth/start", client.jsonOptions("POST")); },
    youtubeSync: function (idempotencyKey) { return client.request("/api/plugins/youtube/sync", client.jsonOptions("POST", {idempotency_key:idempotencyKey || ""})); },
    youtubeDisconnect: function () { return client.request("/api/plugins/youtube/connection", {method:"DELETE"}); },
    discordStatus: function () { return client.request("/api/plugins/discord/status"); },
    discordInstall: function () { return client.request("/api/plugins/discord/install"); },
    discordGuilds: function () { return client.request("/api/plugins/discord/guilds"); },
    discordChannels: function (guildId) { return client.request("/api/plugins/discord/guilds/" + encodeURIComponent(guildId) + "/channels"); },
    discordMessages: function (channelId, limit) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages?limit=" + encodeURIComponent(limit || 20)); },
    discordSend: function (channelId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages", client.jsonOptions("POST", {content:content, confirm:confirm === true})); },
    discordReply: function (channelId, messageId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/reply", client.jsonOptions("POST", {content:content, confirm:confirm === true})); },
    discordEditOwn: function (channelId, messageId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId), client.jsonOptions("PATCH", {content:content, confirm:confirm === true})); },
    discordDeleteOwn: function (channelId, messageId, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/delete", client.jsonOptions("POST", {confirm:confirm === true})); },
    discordReact: function (channelId, messageId, emoji, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/reactions", client.jsonOptions("POST", {emoji:emoji, confirm:confirm === true})); },
    discordCreateThread: function (channelId, messageId, name, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/messages/" + encodeURIComponent(messageId) + "/threads", client.jsonOptions("POST", {name:name, confirm:confirm === true})); },
    discordSendThread: function (channelId, threadId, content, confirm) { return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/threads/" + encodeURIComponent(threadId) + "/messages", client.jsonOptions("POST", {content:content, confirm:confirm === true})); },
    discordSendAttachment: function (channelId, file, content, confirm) { var body = new FormData(); body.set("file", file); body.set("content", content || ""); body.set("confirm", String(confirm === true)); return client.request("/api/plugins/discord/channels/" + encodeURIComponent(channelId) + "/attachments", {method:"POST", body:body}); },
  };
})();
