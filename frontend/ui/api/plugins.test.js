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
  test('artwork requests batch exact IDs and reuse pending and completed metadata',async()=>{
    vi.useFakeTimers();
    try{
      const fetchImpl=vi.fn(async path=>({items:new URL('http://local'+path).searchParams.get('ids').split(',').map(id=>({id,artwork_url:'https://i.scdn.co/image/'+id}))}));
      const api=await loadPluginsApi(fetchImpl),one='A'.repeat(22),two='B'.repeat(22);
      const first=api.spotifyTrackArtwork(one),second=api.spotifyTrackArtwork(two);
      expect(api.spotifyTrackArtwork(one)).toBe(first);expect(fetchImpl).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(25);
      expect((await first).artwork_url).toContain(one);await second;
      expect(fetchImpl).toHaveBeenCalledOnce();expect(api.spotifyTrackArtwork(one)).toBe(first);
      expect(new URL('http://local'+fetchImpl.mock.calls[0][0]).searchParams.get('ids')).toBe(one+','+two);
      await api.spotifyTrackArtwork('../private');expect(fetchImpl).toHaveBeenCalledOnce();
    }finally{vi.useRealTimers();}
  });
  test('artwork failure resolves as unavailable without breaking playback controls',async()=>{
    vi.useFakeTimers();
    try{
      const api=await loadPluginsApi(vi.fn(async()=>{throw new Error('offline');})),id='C'.repeat(22);
      const pending=api.spotifyTrackArtwork(id);await vi.advanceTimersByTimeAsync(25);
      await expect(pending).resolves.toEqual({id,artwork_url:''});
    }finally{vi.useRealTimers();}
  });
  test('ready artwork resolves while only pending images are retried',async()=>{
    vi.useFakeTimers();
    try{
      const one='D'.repeat(22),two='E'.repeat(22);
      const request=vi.fn().mockResolvedValueOnce({items:[{id:one,artwork_url:'https://i.scdn.co/ready'},{id:two,pending:true,artwork_url:''}]}).mockResolvedValue({items:[{id:two,artwork_url:'https://i.scdn.co/later'}]});
      const api=await loadPluginsApi(request),ready=api.spotifyTrackArtwork(one),later=api.spotifyTrackArtwork(two);
      await vi.advanceTimersByTimeAsync(25);await expect(ready).resolves.toMatchObject({artwork_url:'https://i.scdn.co/ready'});
      expect(request).toHaveBeenCalledOnce();await vi.advanceTimersByTimeAsync(250);
      await expect(later).resolves.toMatchObject({artwork_url:'https://i.scdn.co/later'});
      expect(new URL('http://local'+request.mock.calls[1][0]).searchParams.get('ids')).toBe(two);
    }finally{vi.useRealTimers();}
  });
  test('Google install navigates directly and validates the OAuth destination',async()=>{
    const api=await loadPluginsApi(vi.fn());
    const assign=vi.fn();
    vi.stubGlobal('window',{location:{assign}});
    try {
      const authorization_url='https://accounts.google.com/o/oauth2/v2/auth?state=fixture';
      api.navigateToGoogle({authorization_url});
      expect(assign).toHaveBeenCalledExactlyOnceWith(authorization_url);
      assign.mockClear();
      api.navigateToGoogle({authorization_url,browser_opened:true});
      expect(assign).not.toHaveBeenCalled();
      window.VellumDesktop={invoke:vi.fn()};
      expect(()=>api.navigateToGoogle({authorization_url})).toThrow('Continue to Google');
      expect(assign).not.toHaveBeenCalled();
      for(const url of ['javascript:alert(1)','https://accounts.google.com.example.test/o/oauth2/v2/auth','https://accounts.google.com/wrong']) {
        expect(()=>api.navigateToGoogle({authorization_url:url})).toThrow('invalid');
      }
    } finally {vi.unstubAllGlobals();}
  });
  test('Google connection management uses guarded uncached adapter calls',async()=>{
    const fetchImpl=vi.fn(async(path,options)=>({path,options}));const api=await loadPluginsApi(fetchImpl);
    expect(await api.googleStatus()).toMatchObject({path:'/api/plugins/google/status',options:{cache:'no-store',headers:{'X-Vellum-Google':'1'}}});
    expect((await api.googleOAuthStatus('flow/a')).path).toBe('/api/plugins/google/oauth/status?flow_id=flow%2Fa');
  });
  test('keeps Product Hunt secret staging local and uncached',async()=>{
    const fetchImpl=vi.fn(async(path,options)=>({path,options}));
    const api=await loadPluginsApi(fetchImpl);
    const result=await api.productHuntStage('fixture-only-token');
    expect(result.path).toBe('/api/plugins/producthunt/credentials/stage');
    expect(result.options).toMatchObject({method:'POST',body:{token:'fixture-only-token'},cache:'no-store',headers:{'X-Vellum-ProductHunt':'1'}});
    const read=await api.productHuntRead({operation:'posts',limit:3});
    expect(read.path).toBe('/api/plugins/producthunt/read');
    expect(read.options.body).not.toHaveProperty('token');
  });
  test('bounds catalog reads so an unavailable backend can offer retry',async()=>{
    const fetchImpl=vi.fn(async()=>({plugins:[]}));
    const api=await loadPluginsApi(fetchImpl);
    await api.list();
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/plugins');
    expect(fetchImpl.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });
  test("reads local browser-history status without caching", async () => {
    const fetchImpl = vi.fn(async (path, options) => ({path, options}));
    const api = await loadPluginsApi(fetchImpl);
    await api.youtubeHistoryStatus();
    expect(fetchImpl).toHaveBeenCalledWith('/api/plugins/youtube/history/status', {cache:'no-store'});
  });
  test("coalesces overlapping Next clicks into one receipt-backed command", async () => {
    const api = await loadPluginsApi(vi.fn());
    let finish;
    window.VellumApi.appActions = {dispatch:vi.fn(() => new Promise(resolve => {finish=resolve;}))};
    const first = api.spotifyAction({action:'next'});
    const second = api.spotifyAction({action:'next'});
    expect(window.VellumApi.appActions.dispatch).toHaveBeenCalledTimes(1);
    finish({status:'applied',result:{changed:true}});
    await Promise.all([first,second]);
    expect(window.VellumApi.appActions.dispatch.mock.calls[0][0]).toMatchObject({action_id:'spotify.playback.control',arguments:{action:'next'}});
    expect(window.VellumApi.appActions.dispatch.mock.calls[0][0].request_id).toBeTruthy();
  });
  test("keeps Spotify SDK tokens behind the playback adapter with no caching", async () => {
    const fetchImpl = vi.fn(async (path, options) => ({path, options}));
    const api = await loadPluginsApi(fetchImpl);
    const token = await api.spotifyPlaybackToken();
    expect(token.path).toBe('/api/plugins/spotify/playback/token');
    expect(token.options).toMatchObject({method:'POST',cache:'no-store',headers:{'X-Vellum-Spotify-Playback':'1'}});
    const device = await api.spotifyPlaybackDevice({owner_id:'owner',device_id:'device'});
    expect(device.options.headers['X-Vellum-Spotify-Playback']).toBe('1');
  });
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

  test("owns Google Calendar OAuth, reads, and confirmed writes", async () => {
    const fetchImpl = vi.fn(async (path, options) => ({ path, options }));
    const api = await loadPluginsApi(fetchImpl);

    await api.calendarStatus(true);
    await api.calendarOAuthStart();
    await api.calendarCalendars();
    await api.calendarEvents({ time_min: "2026-09-10T00:00:00Z", time_max: "2026-09-11T00:00:00Z" });
    await api.calendarCreateEvent({ summary: "Review", start: "2026-09-10T10:00:00Z", end: "2026-09-10T11:00:00Z", confirm: true });
    await api.calendarDeleteEvent("event-1", "primary", true);

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/plugins/google-calendar/status?probe=true");
    expect(fetchImpl.mock.calls[1][0]).toBe("/api/plugins/google-calendar/oauth/start");
    expect(fetchImpl.mock.calls[2][0]).toBe("/api/plugins/google-calendar/calendars");
    expect(fetchImpl.mock.calls[3][0]).toContain("/api/plugins/google-calendar/events?");
    expect(fetchImpl.mock.calls[4][0]).toBe("/api/plugins/google-calendar/events");
    expect(fetchImpl.mock.calls[5][0]).toBe("/api/plugins/google-calendar/events/event-1/delete");
    expect(fetchImpl.mock.calls[5][1].body.confirm).toBe(true);
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

test("Calendar availability stays inside the plugin adapter", async () => {
  const fetchImpl = vi.fn(async (path, options) => ({path, options}));
  const api = await loadPluginsApi(fetchImpl);
  const body={start:"2026-10-02T15:00:00+05:30",end:"2026-10-02T15:30:00+05:30"};
  await api.calendarAvailability(body);
  expect(fetchImpl).toHaveBeenCalledWith("/api/plugins/google-calendar/availability",{method:"POST",body});
});
