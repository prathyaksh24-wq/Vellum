import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';

const source=readFileSync(resolve('../design/Velllum/uploads/api/voice.js'),'utf8');
let api,processor,tracks,request;
const endpoints={dictation_status:'/status',dictation_prepare:'/prepare',dictation_transcribe:'/transcribe'};
beforeEach(() => {
  tracks=[{stop:vi.fn()}];
  class Context {
    constructor(){this.sampleRate=16000;this.destination={};}
    resume(){return Promise.resolve();}
    close(){return Promise.resolve();}
    createMediaStreamSource(){return {connect:vi.fn(),disconnect:vi.fn()};}
    createScriptProcessor(){processor={connect:vi.fn(),disconnect:vi.fn()};return processor;}
    createGain(){return {gain:{},connect:vi.fn(),disconnect:vi.fn()};}
  }
  window.AudioContext=Context;
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn(async()=>({getAudioTracks:()=>tracks,getTracks:()=>tracks}))}});
  request=vi.fn(async(path)=>path==='/api/capabilities' ? {features:{voice:{enabled:true,endpoints}}} : path==='/status' ? {available:true,max_input_seconds:300} : path==='/prepare' ? {state:'starting'} : {text:'Dictated words.'});
  window.VellumApi={client:{request,backendBase:()=>''}};
  Function(source)();api=window.VellumApi.voice;
});
afterEach(()=>{delete window.AudioContext;vi.restoreAllMocks();});
function frame(value=0.1){processor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(1600).fill(value)}});}
function bytes(blob){return new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsArrayBuffer(blob);});}

test('a Kannada selection made during capture reaches transcription and reports its actual mode',async()=>{
  let language='auto';
  const onLanguage=vi.fn();
  request.mockImplementation(async path=>path==='/api/capabilities' ? {features:{voice:{enabled:true,endpoints}}} : path==='/status' ? {available:true} : path==='/transcribe' ? {text:'Kannada draft',language:'kn',requested_language:'kn'} : {});
  const recorder=api.createDictation({getLanguage:()=>language,onLanguage});
  await recorder.start();frame();language='kn';await recorder.done();
  expect(request.mock.calls.find(([path])=>path==='/transcribe')[1].body.get('language')).toBe('kn');
  expect(onLanguage).toHaveBeenCalledWith('kn','kn');
});

test('failed history storage still inserts the completed transcript and shows the save failure',async()=>{
  const onTranscript=vi.fn(),onChange=vi.fn();
  request.mockImplementation(async path=>path==='/api/capabilities' ? {features:{voice:{enabled:true,endpoints}}} : path==='/status' ? {available:true} : path==='/transcribe' ? {text:'Keep this draft.',history_error:'History could not be saved.'} : {});
  const recorder=api.createDictation({onTranscript,onChange});await recorder.start();frame();await recorder.done();
  expect(onTranscript).toHaveBeenCalledWith('Keep this draft.');
  expect(onChange.mock.lastCall[0]).toMatchObject({state:'error',error:'History could not be saved.'});
});

test('pause excludes audio, resume keeps earlier audio and Done returns a draft after releasing the microphone',async()=>{
  const onChange=vi.fn(),onTranscript=vi.fn();
  const recorder=api.createDictation({onChange,onTranscript});
  await recorder.start();frame();
  expect(onChange.mock.lastCall[0]).toMatchObject({state:'recording',seconds:0.1});
  expect(onChange.mock.lastCall[0].levels[0]).toBeGreaterThan(0);
  recorder.pause();frame(0.9);recorder.resume();frame(0.2);
  await recorder.done();
  const upload=request.mock.calls.find(([path])=>path==='/transcribe')[1];
  const view=new DataView(await bytes(upload.body.get('audio')));
  expect(view.getUint32(40,true)).toBe(9600); // Two 0.1s frames at 24kHz PCM16.
  expect(tracks[0].stop).toHaveBeenCalledTimes(1);
  expect(onTranscript).toHaveBeenCalledExactlyOnceWith('Dictated words.');
  expect(request.mock.calls.map(([path])=>path)).toEqual(['/api/capabilities','/status','/prepare','/transcribe']);
  expect(onChange.mock.lastCall[0].state).toBe('idle');
});

test('Cancel aborts transcription and discards a late response',async()=>{
  let resolveTranscript;
  request.mockImplementation(async path=>path==='/api/capabilities' ? {features:{voice:{enabled:true,endpoints}}} : path==='/status' ? {available:true} : path==='/prepare' ? {} : new Promise(resolve=>{resolveTranscript=resolve;}));
  const onTranscript=vi.fn(),recorder=api.createDictation({onTranscript});
  await recorder.start();frame();
  const finishing=recorder.done();
  await vi.waitFor(()=>expect(resolveTranscript).toBeTypeOf('function'));
  const signal=request.mock.calls.find(([path])=>path==='/transcribe')[1].signal;
  await recorder.cancel();
  expect(signal.aborted).toBe(true);
  resolveTranscript({text:'Must not enter the draft.'});await finishing;
  expect(onTranscript).not.toHaveBeenCalled();
});

test('Cancel while microphone permission is pending releases a late microphone stream',async()=>{
  let grant;
  navigator.mediaDevices.getUserMedia.mockImplementation(()=>new Promise(resolve=>{grant=resolve;}));
  const recorder=api.createDictation();
  const starting=recorder.start();
  await vi.waitFor(()=>expect(grant).toBeTypeOf('function'));
  await recorder.cancel();
  grant({getAudioTracks:()=>tracks,getTracks:()=>tracks});await starting;
  expect(tracks[0].stop).toHaveBeenCalledTimes(1);
  expect(request.mock.calls.some(([path])=>path==='/transcribe')).toBe(false);
});

test('missing installation and empty speech have actionable errors',async()=>{
  const onChange=vi.fn(),onTranscript=vi.fn();
  request.mockImplementation(async path=>path==='/api/capabilities' ? {features:{voice:{enabled:true,endpoints}}} : {available:false,detail:'Install local Whisper.'});
  const recorder=api.createDictation({onChange,onTranscript});await recorder.start();
  expect(onChange.mock.lastCall[0]).toMatchObject({state:'error',error:'Install local Whisper.'});
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  request.mockImplementation(async path=>path==='/api/capabilities' ? {features:{voice:{enabled:true,endpoints}}} : path==='/status' ? {available:true} : {text:''});
  await recorder.start();frame(0);await recorder.done();
  expect(onChange.mock.lastCall[0].error).toContain('No speech was recognized');
  expect(onTranscript).not.toHaveBeenCalled();
});

test('inserting dictation preserves text typed during transcription',()=>{
  expect(api.appendDictation('Draft with my latest edit.','  Dictated words.  ')).toBe('Draft with my latest edit. Dictated words.');
  expect(api.appendDictation('Draft\n','More.')).toBe('Draft\nMore.');
  expect(api.appendDictation('Unchanged',' ')).toBe('Unchanged');
});


test('composer without a language control leaves the hint to saved server preferences',async()=>{
  const recorder=api.createDictation();await recorder.start();frame();await recorder.done();
  expect(request.mock.calls.find(([path])=>path==='/transcribe')[1].body.has('language')).toBe(false);
});

test('releasing a shortcut during microphone connection releases late capture even with no speech',async()=>{
  let grant; navigator.mediaDevices.getUserMedia.mockImplementation(()=>new Promise(resolve=>{grant=resolve;}));
  const onTranscript=vi.fn(),onChange=vi.fn(),recorder=api.createDictation({onTranscript,onChange});
  const start=recorder.start();await vi.waitFor(()=>expect(grant).toBeTypeOf('function'));
  await recorder.done();
  grant({getAudioTracks:()=>tracks,getTracks:()=>tracks});await start;
  await vi.waitFor(()=>expect(onChange.mock.lastCall[0].state).toBe('error'));
  expect(onTranscript).not.toHaveBeenCalled();
  expect(tracks[0].stop).toHaveBeenCalledTimes(1);
});
