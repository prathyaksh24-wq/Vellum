import {afterEach,beforeEach,expect,test,vi} from 'vitest';
let controller;
const flush=async () => {for(let i=0;i<15;i++)await Promise.resolve();};
async function fixture(state={}) {
  await import('../../design/Velllum/uploads/components/local-music-playback.js');
  const audio=new EventTarget();Object.assign(audio,{paused:true,ended:false,currentTime:0,duration:120,volume:1,readyState:1,src:''});
  audio.pause=vi.fn(() => {audio.paused=true;});audio.load=vi.fn();audio.play=vi.fn(async () => {audio.paused=false;});
  const player={revision:1,queue:['song-one','song-two'],index:0,seconds:0,volume:.7,playing:true,repeat:'off',shuffle:false,...state};
  const api={report:vi.fn(async () => ({accepted:true,player:{...player}})),audioUrl:id=>'http://127.0.0.1/audio/'+id,action:vi.fn(async (name,args) => {
    player.revision++;if(args.action==='pause')player.playing=false;if(args.action==='next')player.index++;
    return {status:'applied'};
  })};
  const beforePlay=vi.fn(async () => {}),onChange=vi.fn();
  controller=window.VellumLocalMusicPlayback.create({api,audio,ownerId:'test_owner_123456789',beforePlay,onChange});
  await controller.start();await flush();
  return {api,audio,player,beforePlay,onChange};
}
beforeEach(() => {vi.useFakeTimers();vi.resetModules();});
afterEach(() => {controller?.destroy();vi.useRealTimers();});

test('claims an owner before playing and reports actual audio state',async () => {
  const f=await fixture();
  expect(f.api.report).toHaveBeenCalledBefore(f.audio.play);
  expect(f.beforePlay).toHaveBeenCalledBefore(f.audio.play);
  expect(f.audio.src).toContain('song-one');
  f.audio.currentTime=35;await vi.advanceTimersByTimeAsync(1000);
  expect(f.api.report).toHaveBeenLastCalledWith(expect.objectContaining({seconds:35,playing:true}));
});
test('a shared window pauses and never applies another owner’s playback',async () => {
  const f=await fixture({playing:false});f.api.report.mockResolvedValue({accepted:false,player:{...f.player,playing:true}});
  f.player.revision++;await vi.advanceTimersByTimeAsync(1000);
  expect(f.audio.play).not.toHaveBeenCalled();expect(f.onChange).toHaveBeenLastCalledWith(expect.objectContaining({shared:true}));
});
test('a blocked audio start is visible and a new Resume command can retry',async () => {
  const f=await fixture({playing:false});f.audio.play.mockRejectedValueOnce(new Error('autoplay'));
  f.player.playing=true;f.player.revision++;await vi.advanceTimersByTimeAsync(1000);
  expect(controller.snapshot().error).toContain('Press Resume');
  f.player.revision++;await vi.advanceTimersByTimeAsync(1000);expect(controller.snapshot().error).toBe('');
});
test('pause state does not turn itself back on during polling',async () => {
  const f=await fixture();await controller.pause();await vi.advanceTimersByTimeAsync(4000);
  expect(f.audio.play).toHaveBeenCalledTimes(1);expect(f.audio.paused).toBe(true);
});
test('network loss pauses before ownership lease expires',async () => {
  const f=await fixture();f.api.report.mockRejectedValue(new Error('offline'));
  await vi.advanceTimersByTimeAsync(4500);expect(f.audio.paused).toBe(true);expect(controller.snapshot().error).toContain('service is unavailable');
});
test('last song stops with repeat off and next transitions keep the queue',async () => {
  const f=await fixture({index:1});f.audio.ended=true;f.audio.dispatchEvent(new Event('ended'));await flush();
  expect(f.api.action).toHaveBeenCalledWith('playback',{action:'pause'});
  expect(f.player.queue).toEqual(['song-one','song-two']);
});
test('repeat-one seeks to the beginning instead of choosing another track',async () => {
  const f=await fixture({repeat:'one'});f.audio.ended=true;f.audio.dispatchEvent(new Event('ended'));await flush();
  expect(f.api.action).toHaveBeenCalledWith('playback',{action:'seek',seconds:0});
});
test('destroy releases audio and cancels subsequent polling',async () => {
  const f=await fixture();controller.destroy();const count=f.api.report.mock.calls.length;
  await vi.advanceTimersByTimeAsync(20000);expect(f.api.report).toHaveBeenCalledTimes(count);expect(f.audio.paused).toBe(true);
});
