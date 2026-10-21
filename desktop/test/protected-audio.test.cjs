const {test}=require('node:test');
const assert=require('node:assert/strict');
const {initializeProtectedAudio}=require('../electron/protected-audio.cjs');

test('desktop waits for Widevine before a playback window can open',async()=>{
  let resolve,requested;
  const pending=new Promise(done=>resolve=done);
  const components={WIDEVINE_CDM_ID:'widevine',whenReady(ids){requested=ids;return pending;}};
  let initialized=false;
  const ready=initializeProtectedAudio({components}).then(result=>{initialized=true;return result;});
  await Promise.resolve();
  assert.equal(initialized,false);
  assert.deepEqual(requested,['widevine']);
  resolve([]);
  assert.deepEqual(await ready,{status:'ready'});
});

test('stock Electron is explicitly unsupported and component failures stay recoverable',async()=>{
  assert.deepEqual(await initializeProtectedAudio({}),{status:'unsupported'});
  await assert.rejects(initializeProtectedAudio({components:{WIDEVINE_CDM_ID:'widevine',whenReady:async()=>{throw Error('download failed')}}}),/download failed/);
});

test('a stalled component download cannot block desktop startup indefinitely',async()=>{
  await assert.rejects(initializeProtectedAudio({components:{WIDEVINE_CDM_ID:'widevine',whenReady:()=>new Promise(()=>{})}},{timeoutMs:10}),/timed out/);
});
