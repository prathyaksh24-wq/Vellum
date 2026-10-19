import {afterEach, beforeEach, describe, expect, test, vi} from 'vitest';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const uploads = resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads');
// Compile in Node's realm: jsdom's Uint8Array differs from Node's TextEncoder.
const compiled = Object.fromEntries(['PatternWaves', 'Particles'].map(name => [name,
  execFileSync(process.execPath, ['-e', "const fs=require('node:fs');const esbuild=require('esbuild');process.stdout.write(esbuild.transformSync(fs.readFileSync(process.argv[1],'utf8'),{loader:'jsx',jsx:'transform'}).code)", resolve(uploads, `components/${name}.jsx`)], {encoding: 'utf8'}),
]));
let root;
let container;
let frames;
let graphics;

function mockGraphics(webgl2 = true) {
  const gl = {
    canvas: document.createElement('canvas'),
    getExtension: vi.fn(() => ({loseContext: vi.fn()})),
    clearColor: vi.fn(), deleteFramebuffer: vi.fn(), deleteTexture: vi.fn(),
  };
  class Texture { constructor() { this.texture = {}; } }
  class RenderTarget {
    constructor(_gl, options) { Object.assign(this, options); this.texture = new Texture(); }
  }
  class Renderer {
    constructor() { this.gl = gl; this.isWebgl2 = webgl2; }
    setSize(w, h) { gl.canvas.width = w; gl.canvas.height = h; }
    render = vi.fn();
  }
  return {gl, Renderer, Texture, RenderTarget, Triangle: class {}, Program: class {}, Mesh: class {}};
}

beforeEach(() => {
  frames = new Map();
  let frameId = 0;
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { frames.set(++frameId, callback); return frameId; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn(id => frames.delete(id)));
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} });
  vi.stubGlobal('matchMedia', vi.fn(() => ({matches: false})));
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  window.VellumUI = {};
  for (const name of ['PatternWaves', 'Particles']) {
    new Function(compiled[name])();
  }
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  graphics = mockGraphics();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('React Bits background lifecycle', () => {
  test('a delayed graphics load cannot mount after leaving the background', async () => {
    let resolve;
    const loading = new Promise(done => { resolve = done; });
    await act(async () => root.render(React.createElement(window.VellumUI.PatternWaves, {loadGraphics: () => loading})));
    const detached = container.firstChild;
    await act(async () => root.render(null));
    await act(async () => resolve(graphics));
    expect(detached.querySelector('canvas')).toBeNull();
    expect(frames.size).toBe(0);
  });

  test.each(['rejected', 'unsupported'])('%s OGL leaves a usable fallback surface', async kind => {
    const loadGraphics = kind === 'rejected' ? () => Promise.reject(new Error('offline')) : () => mockGraphics(false);
    await act(async () => root.render(React.createElement(window.VellumUI.PatternWaves, {loadGraphics})));
    expect(container.querySelector('.pattern-waves')).not.toBeNull();
    expect(container.querySelector('canvas')).toBeNull();
    expect(frames.size).toBe(0);
  });

  test('reduced motion renders a visible still frame and releases it on switch', async () => {
    window.matchMedia.mockReturnValue({matches: true});
    await act(async () => root.render(React.createElement(window.VellumUI.PatternWaves, {loadGraphics: () => graphics, intro: false})));
    expect(container.querySelector('canvas')).not.toBeNull();
    const callback = frames.values().next().value;
    frames.clear();
    callback(1000);
    expect(frames.size).toBe(0);
    expect(graphics.gl.canvas.getAttribute('aria-hidden')).toBe('true');
    await act(async () => root.render(null));
    expect(graphics.gl.canvas.parentNode).toBeNull();
    expect(graphics.gl.deleteFramebuffer).toHaveBeenCalled();
  });

  test('Particles remains decorative and usable without WebGL', async () => {
    await act(async () => root.render(React.createElement(window.VellumUI.Particles)));
    expect(container.querySelector('.particles-canvas').getAttribute('aria-hidden')).toBe('true');
    expect(frames.size).toBe(0);
  });

  test('Particles draws a reduced-motion still frame without a continuing render loop', async () => {
    window.matchMedia.mockReturnValue({matches: true});
    const calls = {};
    const gl = new Proxy({COMPILE_STATUS: 1, LINK_STATUS: 2, ACTIVE_UNIFORMS: 3}, {
      get(target, key) {
        if (key in target) return target[key];
        if (key.toUpperCase() === key) return 0;
        return calls[key] ||= vi.fn((...args) => {
          if (key === 'getShaderParameter') return true;
          if (key === 'getProgramParameter') return args[1] === 3 ? 0 : true;
          if (key === 'getExtension') return null;
          if (key.startsWith('create')) return {};
        });
      },
    });
    HTMLCanvasElement.prototype.getContext.mockImplementation(kind => kind === 'webgl2' ? gl : null);
    await act(async () => root.render(React.createElement(window.VellumUI.Particles, {particleCount: 5})));
    const callback = frames.values().next().value;
    frames.clear();
    callback(1000);
    expect(calls.drawArraysInstanced).toHaveBeenCalled();
    expect(frames.size).toBe(0);
    await act(async () => root.render(null));
    expect(calls.deleteBuffer).toHaveBeenCalledTimes(5);
    expect(calls.deleteProgram).toHaveBeenCalledTimes(2);
  });
});

test.each(['pattern-waves', 'particles'])('%s uses the existing device setting receipt and persists across reload', async id => {
  vi.resetModules();
  await import('../../design/Velllum/uploads/components/app-action-runtime.js');
  const AppActions = window.VellumUI.AppActions;
  const values = new Map();
  const storage = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key)};
  const client = {dispatch: vi.fn(async () => ({status: 'applied', result: {device_settings_patch: {version: 1, base_revision: 0, revision: 1, values: {background: id}}}}))};
  const runtime = AppActions.createDeviceSettingsRuntime({storage, client});
  await runtime.dispatch({background: id});
  expect(client.dispatch.mock.calls[0][0].arguments.patch.background).toBe(id);
  expect(AppActions.createDeviceSettingsRuntime({storage, client: {}}).snapshot().values.background).toBe(id);
});

test('Appearance cards keep a thumbnail until focused and release the live renderer on blur',async()=>{
  const html=readFileSync(resolve(uploads,'Vellum Default Re-designed.html'),'utf8');
  const source=html.slice(html.indexOf('const BackgroundRenderer ='),html.indexOf('const IcNote ='));
  const code=execFileSync(process.execPath,['-e',"const esbuild=require('esbuild');process.stdout.write(esbuild.transformSync(process.argv[1],{loader:'jsx'}).code)",source],{encoding:'utf8'});
  const Card=new Function('React',`const {useState}=React;const IcCheck=()=>null;${code};return BackgroundChoiceCard;`)(React);
  const render=vi.fn(()=>React.createElement('canvas'));
  await act(async()=>root.render(React.createElement(Card,{entry:{id:'galaxy',label:'Galaxy',kind:'shader',component:render},selected:false,onSelect:vi.fn()})));
  expect(render).not.toHaveBeenCalled();
  expect(container.querySelector('img').getAttribute('src')).toBe('assets/backgrounds/previews/galaxy.png');
  await act(async()=>container.querySelector('button').focus());
  expect(render).toHaveBeenCalledTimes(1);
  expect(container.querySelector('canvas')).not.toBeNull();
  await act(async()=>container.querySelector('button').blur());
  expect(container.querySelector('canvas')).toBeNull();
  expect(container.querySelector('img')).not.toBeNull();
});
