import {afterEach, beforeEach, describe, expect, test, vi} from 'vitest';

let controllers;
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

async function fixture(overrides = {}) {
  await import('../../design/Velllum/uploads/components/spotify-playback.js');
  let sdkPlayer;
  const order = [];
  class Player {
    constructor(config) {
      this.config = config; this.listeners = {}; sdkPlayer = this;
      this.connect = vi.fn(async () => { config.getOAuthToken(this.tokenCallback); return true; });
      this.disconnect = vi.fn(); this.tokenCallback = vi.fn();
      this.activateElement = vi.fn(() => { order.push('activate'); return Promise.resolve(); });
    }
    addListener(name, callback) { this.listeners[name] = callback; }
  }
  const api = {
    spotifyPlaybackToken: vi.fn(async () => ({access_token:'fresh-access'})),
    spotifyPlaybackDevice: vi.fn(async () => ({status:'ready'})), ...overrides.api,
  };
  const actions = {dispatch: vi.fn(async () => { order.push('dispatch'); return {status:'applied'}; }), ...overrides.actions};
  const onChange = vi.fn(), onPlayer = vi.fn();
  const controller = window.VellumSpotifyPlayback.create({api, actions, onChange, onPlayer, ownerId:'test-owner', pageUrl:overrides.pageUrl, loadSDK: async () => ({Player})});
  controllers.push(controller);
  await controller.prepare();
  return {controller, player:sdkPlayer, api, actions, order, onChange, onPlayer};
}

describe('Vellum Spotify Connect player lifecycle', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.resetModules(); controllers = []; });
  afterEach(async () => { controllers.forEach(c => c.dispose()); await flush(); vi.useRealTimers(); });

  test('direct HTML file previews explain the required server origin before loading the SDK', async () => {
    const f = await fixture({pageUrl:'file:///C:/Vellum/design/Vellum.html'});
    expect(f.player).toBeUndefined();
    expect(f.controller.getSnapshot().status).toBe('file_preview');
    await f.controller.enable();
    expect(f.actions.dispatch).not.toHaveBeenCalled();
    expect(f.api.spotifyPlaybackToken).not.toHaveBeenCalled();
  });

  test('SDK volume is reflected in UI and trusted backend observations', async () => {
    const f = await fixture();
    f.player.getVolume = vi.fn(async () => .23);
    await f.controller.enable(); await f.player.listeners.ready({device_id:'vellum-device'});
    await vi.advanceTimersByTimeAsync(20000); await flush();
    expect(f.onPlayer).toHaveBeenCalledWith(expect.objectContaining({device:expect.objectContaining({volume_percent:23})}));
  });

  test('requested local volume uses SDK and acknowledges measured value', async () => {
    const f = await fixture({api:{spotifyPlaybackDevice:vi.fn(async () => ({status:'ready',volume_request:{id:'v1',percent:17}}))}});
    let volume=.5;
    f.player.setVolume = vi.fn(async v => {volume=v;});
    f.player.getVolume = vi.fn(async () => volume);
    await f.controller.enable(); await f.player.listeners.ready({device_id:'vellum-device'}); await flush();
    expect(f.player.setVolume).toHaveBeenCalledTimes(1);
    expect(f.player.setVolume).toHaveBeenCalledWith(.17);
    expect(f.api.spotifyPlaybackDevice).toHaveBeenCalledWith(expect.objectContaining({volume_ack:'v1',volume_percent:17}));
  });

  test('volume-only heartbeats do not keep an old song observation fresh', async () => {
    const f=await fixture(); f.player.getVolume=vi.fn(async () => .23);
    f.player.getCurrentState=vi.fn(async () => null);
    await f.controller.enable(); await f.player.listeners.ready({device_id:'vellum-device'});
    f.player.listeners.player_state_changed({paused:false,position:0,duration:10000,
      track_window:{current_track:{id:'song',uri:'spotify:track:song',name:'Song',artists:[]}}});
    await flush();
    f.api.spotifyPlaybackDevice.mockClear();
    await vi.advanceTimersByTimeAsync(7000);
    expect(f.api.spotifyPlaybackDevice.mock.calls.every(([body]) => !body.observation)).toBe(true);
  });

  test('a rejected page origin is not misreported as revoked Spotify authorization', async () => {
    const f = await fixture({api:{spotifyPlaybackToken:vi.fn(async () => {throw Object.assign(new Error('forbidden'),{status:403});})}});
    await f.controller.enable(); await flush();
    f.player.listeners.authentication_error();
    expect(f.controller.getSnapshot().status).toBe('origin_error');
    await vi.advanceTimersByTimeAsync(180000);
    expect(f.player.connect).toHaveBeenCalledTimes(1);
  });

  test('prepares without connecting and activates audio synchronously before the typed action', async () => {
    const f = await fixture();
    expect(f.player.connect).not.toHaveBeenCalled();
    const enabled = f.controller.enable();
    expect(f.order).toEqual(['activate']);
    await enabled; await flush();
    expect(f.order).toEqual(['activate', 'dispatch']);
    expect(f.actions.dispatch).toHaveBeenCalledWith({action_id:'spotify.playback.session', arguments:{owner_id:'test-owner',operation:'enable'}}, {source:'ui'});
    expect(f.player.tokenCallback).toHaveBeenCalledWith('fresh-access');
    expect(f.controller.getSnapshot().ready).toBe(false);
    await f.player.listeners.ready({device_id:'vellum-device'});
    expect(f.controller.getSnapshot()).toMatchObject({status:'ready',ready:true});
    expect(f.api.spotifyPlaybackDevice).toHaveBeenCalledWith(expect.objectContaining({owner_id:'test-owner',device_id:'vellum-device'}));
  });

  test('every SDK token request fetches a fresh backend token without storing it', async () => {
    const f = await fixture(); await f.controller.enable(); await flush();
    f.api.spotifyPlaybackToken.mockResolvedValueOnce({access_token:'rotated-access'});
    const callback = vi.fn(); f.player.config.getOAuthToken(callback); await flush();
    expect(callback).toHaveBeenCalledWith('rotated-access');
    expect(JSON.stringify(f.controller.getSnapshot())).not.toContain('access');
    expect(localStorage.getItem('spotify-access-token')).toBeNull();
  });

  test('a natural play request activates immediately and waits for the registered device', async () => {
    const f = await fixture();
    const request = window.VellumSpotifyPlayback.beginRequest('play Rain Over Me');
    expect(f.order).toEqual(['activate']);
    let done = false; request.ready.then(() => { done = true; });
    await flush(); expect(done).toBe(false);
    await f.player.listeners.ready({device_id:'vellum-device'});
    await request.ready; expect(done).toBe(true);
    expect(f.actions.dispatch).toHaveBeenCalledWith(expect.objectContaining({action_id:'spotify.playback.session'}), {source:'ui'});
  });

  test.each(['can u play j cole latest album', 'latest album from j cole', 'latest album from lil baby', 'latest album from The Game'])('album request %s activates audio before chat and waits for the device', async message => {
    const f = await fixture();
    const request = window.VellumSpotifyPlayback.beginRequest(message);
    expect(request).toBeDefined();
    expect(f.order).toEqual(['activate']);
    await flush();
    await f.player.listeners.ready({device_id:'vellum-device'});
    await request.ready;
    expect(f.controller.getSnapshot().ready).toBe(true);
  });

  test('mixed requests activate music while unrelated play requests leave the player alone', async () => {
    const f = await fixture();
    expect(window.VellumSpotifyPlayback.beginRequest('play chess')).toBeUndefined();
    expect(window.VellumSpotifyPlayback.beginRequest('what videos have I watched')).toBeUndefined();
    const request = window.VellumSpotifyPlayback.beginRequest('what videos have I watched and play a song');
    await flush(); await f.player.listeners.ready({device_id:'vellum-device'}); await request.ready;
    expect(f.player.activateElement).toHaveBeenCalledTimes(1);
  });

  test('casual music commands activate audio while other provider aliases leave Spotify alone',async () => {
    const f=await fixture();
    for(const name of ['yt music','YT music/player','yt player','apple music']) {
      expect(window.VellumSpotifyPlayback.beginRequest('play a song on '+name)).toBeUndefined();
      expect(window.VellumSpotifyPlayback.beginRequest('On '+name+', play Blinding Lights')).toBeUndefined();
    }
    const request=window.VellumSpotifyPlayback.beginRequest('yo chuck on a tune from my Hindi playlist pls');
    expect(request).toBeDefined();
    expect(f.order).toEqual(['activate']);
    await flush();await f.player.listeners.ready({device_id:'vellum-device'});await request.ready;
  });

  test('polite recommendations and controls do not automatically enable playback',async () => {
    const f=await fixture();
    for(const message of ['Could you recommend music for winding down?','Would you pause the song?','Can you tell me which song is playing?']) {
      expect(window.VellumSpotifyPlayback.beginRequest(message)).toBeUndefined();
    }
    expect(f.player.activateElement).not.toHaveBeenCalled();
  });

  test.each([
    'Would you mind picking a tune from whichever of my playlists you fancy?',
    'Could you put Dynamite by BTS on for me?',
    'play a song from 69',
    'play a song from my playslist',
    'can u play j cole latest album',
  ])('persona playback automatically activates and registers the Vellum device: %s',async message => {
    const f=await fixture();
    const request=window.VellumSpotifyPlayback.beginRequest(message);
    expect(request).toBeDefined();
    expect(f.order).toEqual(['activate']);
    await flush();await f.player.listeners.ready({device_id:'vellum-device'});await request.ready;
    expect(f.controller.getSnapshot().ready).toBe(true);
    expect(f.api.spotifyPlaybackDevice).toHaveBeenCalledWith(expect.objectContaining({device_id:'vellum-device'}));
  });

  test('explicit stop releases local playback only after Spotify verifies it is paused', async () => {
    const f = await fixture({api:{spotifyPlayer:vi.fn(async () => ({is_playing:false,device:{id:'vellum-device'}}))}});
    await f.controller.enable(); await f.player.listeners.ready({device_id:'vellum-device'});
    const request = window.VellumSpotifyPlayback.beginRequest('stop the music'); await request.ready;
    expect(f.controller.getSnapshot().enabled).toBe(true);
    await request.complete({tools:['music_agent']});
    expect(f.controller.getSnapshot().enabled).toBe(false);
    expect(f.actions.dispatch).toHaveBeenLastCalledWith(expect.objectContaining({arguments:{owner_id:'test-owner',operation:'disable'}}), {source:'ui'});
  });

  test('pause keeps the player ready and a failed stop cannot disable ongoing music', async () => {
    const f = await fixture({api:{spotifyPlayer:vi.fn(async () => ({is_playing:true,device:{id:'vellum-device'}}))}});
    await f.controller.enable(); await f.player.listeners.ready({device_id:'vellum-device'});
    expect(window.VellumSpotifyPlayback.beginRequest('pause')).toBeUndefined();
    await window.VellumSpotifyPlayback.beginRequest('stop').complete({tools:['music_agent']});
    expect(f.controller.getSnapshot().ready).toBe(true);
  });

  test('automatic activation has a total time limit even when SDK connect stalls', async () => {
    const f = await fixture(); f.player.connect.mockImplementation(() => new Promise(() => {}));
    const request = window.VellumSpotifyPlayback.beginRequest('play a song');
    const failed = expect(request.ready).rejects.toMatchObject({vellumPlaybackError:true});
    await vi.advanceTimersByTimeAsync(12000); await failed;
  });

  test('a play request waits for initial component registration rather than using a phone', async () => {
    await import('../../design/Velllum/uploads/components/spotify-playback.js');
    const request = window.VellumSpotifyPlayback.beginRequest('play a song');
    const f = await fixture(); await flush();
    await f.player.listeners.ready({device_id:'vellum-device'}); await request.ready;
    expect(f.controller.getSnapshot().ready).toBe(true);
  });

  test('podcast episode states without track artists or album do not crash the player', async () => {
    const f = await fixture(); await f.controller.enable(); await flush();
    const emit = () => f.player.listeners.player_state_changed({paused:false, position:0, duration:1000,
      track_window:{current_track:{id:'ep1', uri:'spotify:episode:ep1', name:'Travel', images:[{url:'cover'}], show:{name:'WTF'}}, next_tracks:[]}});
    expect(emit).not.toThrow();
    expect(f.onPlayer).toHaveBeenLastCalledWith(expect.objectContaining({track:{id:'ep1',uri:'spotify:episode:ep1',name:'Travel'}, artists:['WTF'],artwork_url:'cover'}));
  });

  test('reports bounded audio health without credentials or track metadata', async () => {
    const f = await fixture(); await f.controller.enable(); await flush();
    await f.player.listeners.ready({device_id:'vellum-device'});
    for (let i=0; i<50; i++) f.player.listeners.player_state_changed({paused:false,position:i*1000,duration:200000,
      track_window:{current_track:{id:'private-track',uri:'spotify:track:private',name:'Private title',artists:[],album:{images:[],name:''}}}});
    f.player.listeners.playback_error(); await flush();
    const body = f.api.spotifyPlaybackDevice.mock.calls.map(call => call[0]).findLast(body => body.diagnostics?.length);
    expect(body.diagnostics).toHaveLength(32);
    expect(body.diagnostics.at(-1).event).toBe('playback_error');
    expect(JSON.stringify(body.diagnostics)).not.toMatch(/fresh-access|private-track|Private title/);
  });

  test('refreshes a rejected token before reconnecting, with bounded authentication recovery', async () => {
    const f = await fixture(); await f.controller.enable();
    f.player.listeners.authentication_error(); await vi.advanceTimersByTimeAsync(1000); await flush();
    expect(f.api.spotifyPlaybackToken).toHaveBeenLastCalledWith(true);
    f.player.listeners.authentication_error(); await vi.advanceTimersByTimeAsync(2000); await flush();
    f.player.listeners.authentication_error(); await flush();
    expect(f.controller.getSnapshot().status).toBe('reauth_required');
    const calls = f.player.connect.mock.calls.length;
    await vi.advanceTimersByTimeAsync(180000);
    expect(f.player.connect).toHaveBeenCalledTimes(calls);
  });

  test('a stalled SDK connection times out and retries instead of hanging forever', async () => {
    const f = await fixture();
    f.player.connect.mockImplementationOnce(() => new Promise(() => {}));
    const pending = f.controller.enable(); await flush();
    await vi.advanceTimersByTimeAsync(30000); await pending;
    expect(f.controller.getSnapshot().status).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(1000);
    expect(f.player.connect).toHaveBeenCalledTimes(2);
  });

  test('renews its device lease while hidden and recovers after not_ready', async () => {
    const f = await fixture(); await f.controller.enable();
    await f.player.listeners.ready({device_id:'first-device'});
    await vi.advanceTimersByTimeAsync(20000);
    expect(f.api.spotifyPlaybackDevice).toHaveBeenLastCalledWith({owner_id:'test-owner',device_id:'first-device'});
    f.player.listeners.not_ready(); await flush();
    expect(f.controller.getSnapshot().ready).toBe(false);
    expect(f.api.spotifyPlaybackDevice).toHaveBeenLastCalledWith(expect.objectContaining({owner_id:'test-owner',device_id:''}));
    await vi.advanceTimersByTimeAsync(1000);
    expect(f.player.connect).toHaveBeenCalledTimes(2);
    await f.player.listeners.ready({device_id:'recovered-device'});
    expect(f.controller.getSnapshot().ready).toBe(true);
  });

  test('shows revoked consent and stops reconnect loops', async () => {
    const f = await fixture({api:{spotifyPlaybackToken: vi.fn(async () => { throw Object.assign(new Error('revoked'), {status:401}); })}});
    await f.controller.enable(); await flush();
    expect(f.controller.getSnapshot().status).toBe('reauth_required');
    await vi.advanceTimersByTimeAsync(180000);
    expect(f.player.connect).toHaveBeenCalledTimes(1);
  });

  test.each(['initialization_error','account_error','autoplay_failed'])('reports %s without retrying indefinitely', async event => {
    const f = await fixture(); await f.controller.enable();
    await f.player.listeners.ready({device_id:'vellum-device'});
    f.player.listeners[event]({message:'unsafe raw diagnostic'}); await flush();
    expect(f.controller.getSnapshot().ready).toBe(false);
    expect(f.controller.getSnapshot().message).not.toContain('unsafe');
    await vi.advanceTimersByTimeAsync(180000);
    expect(f.player.connect).toHaveBeenCalledTimes(1);
    expect(f.api.spotifyPlaybackDevice).toHaveBeenLastCalledWith(expect.objectContaining({owner_id:'test-owner',device_id:''}));
  });

  test('refuses a second window and does not connect it', async () => {
    const f = await fixture({actions:{dispatch: vi.fn(async () => ({status:'failed',message:'Already running in another window'}))}});
    await f.controller.enable();
    expect(f.player.connect).not.toHaveBeenCalled();
    expect(f.controller.getSnapshot()).toMatchObject({status:'busy',enabled:false});
  });

  test('restores its authorized lease after a backend restart', async () => {
    const f = await fixture(); await f.controller.enable();
    f.api.spotifyPlaybackDevice.mockRejectedValueOnce(Object.assign(new Error('owner missing'), {status:409}));
    await f.player.listeners.ready({device_id:'vellum-device'});
    expect(f.actions.dispatch).toHaveBeenCalledTimes(2);
    expect(f.controller.getSnapshot().ready).toBe(true);
  });

  test('a natural play request reuses a ready player in another window', async () => {
    const f = await fixture({
      api:{spotifyPlayer:vi.fn(async () => ({web_playback:{status:'ready',device_id:'other-device'},devices:[{id:'other-device',is_restricted:false}]}))},
      actions:{dispatch:vi.fn(async () => ({status:'failed',message:'Vellum playback is already running in another window'}))},
    });
    await window.VellumSpotifyPlayback.beginRequest('play a song').ready;
    expect(f.controller.getSnapshot()).toMatchObject({status:'shared',enabled:false,ready:false});
    expect(f.player.connect).not.toHaveBeenCalled();
    expect(f.api.spotifyPlayer).toHaveBeenCalledWith(true);
    expect(f.actions.dispatch).toHaveBeenCalledTimes(1);
  });

  test('an unready owner in another window is not reported as usable playback', async () => {
    const f = await fixture({
      api:{spotifyPlayer:vi.fn(async () => ({web_playback:{status:'reconnecting'}}))},
      actions:{dispatch:vi.fn(async () => ({status:'failed',message:'Vellum playback is already running in another window'}))},
    });
    await expect(window.VellumSpotifyPlayback.beginRequest('play a song').ready).rejects.toMatchObject({vellumPlaybackError:true});
    expect(f.controller.getSnapshot().status).toBe('busy');
    expect(f.player.connect).not.toHaveBeenCalled();
  });

  test('a delayed SDK token is discarded when the player is disabled', async () => {
    let finish;
    const f = await fixture({api:{spotifyPlaybackToken: vi.fn(() => new Promise(resolve => {finish = resolve;}))}});
    await f.controller.enable(); await f.controller.disable();
    finish({access_token:'late-access'}); await flush();
    expect(f.player.tokenCallback).not.toHaveBeenCalled();
    expect(f.controller.getSnapshot()).toMatchObject({enabled:false,ready:false});
  });

  test('late ready events after disposal cannot advertise an active device', async () => {
    const f = await fixture(); await f.controller.enable(); f.controller.dispose();
    await f.player.listeners.ready({device_id:'late-device'}); await flush();
    expect(f.api.spotifyPlaybackDevice).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(180000);
    expect(f.player.connect).toHaveBeenCalledTimes(1);
  });
});
