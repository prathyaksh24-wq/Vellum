import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const uploads = resolve(dirname(fileURLToPath(import.meta.url)), '../../design/Velllum/uploads');
const provenance = JSON.parse(readFileSync(resolve(uploads, 'assets/backgrounds/dvk/provenance.json'), 'utf8'));
const compiled = execFileSync(process.execPath, ['-e', "const fs=require('node:fs');const esbuild=require('esbuild');process.stdout.write(esbuild.transformSync(fs.readFileSync(process.argv[1],'utf8'),{loader:'jsx'}).code)", resolve(uploads, 'components/DvkMotionBackground.jsx')], {encoding:'utf8'});
let root, container, frames, images, gl, lostContext, resize, intersection, motion;

function graphics() {
  const calls = {};
  return new Proxy({}, {get(target, key) {
    if (typeof key !== 'string') return target[key];
    if (key.toUpperCase() === key) return key;
    return calls[key] ||= vi.fn(() => {
      if (key === 'getExtension') return null;
      if (key === 'getShaderParameter' || key === 'getProgramParameter') return true;
      if (key === 'checkFramebufferStatus') return 'FRAMEBUFFER_COMPLETE';
      if (key.startsWith('create')) return {};
      if (key === 'getUniformLocation') return {};
    });
  }});
}

beforeEach(() => {
  frames = new Map();
  images = [];
  let id = 0;
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { frames.set(++id, callback); return id; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn(id => frames.delete(id)));
  vi.stubGlobal('ResizeObserver', class { constructor(callback) { resize = callback; } observe() {} disconnect() {} });
  vi.stubGlobal('IntersectionObserver', class { constructor(callback) { intersection = callback; } observe() {} disconnect() {} });
  motion = {matches:false, addEventListener:vi.fn(), removeEventListener:vi.fn()};
  vi.stubGlobal('matchMedia', vi.fn(() => motion));
  vi.stubGlobal('Image', class { constructor() { this.width = 1920; this.height = 1080; images.push(this); } });
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  gl = graphics();
  lostContext = vi.fn();
  gl.getExtension.mockImplementation(name => name === 'WEBGL_lose_context' ? {loseContext:lostContext} : null);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(kind => ['webgl2','webgl'].includes(kind) ? gl : null);
  vi.spyOn(HTMLCanvasElement.prototype, 'clientWidth', 'get').mockReturnValue(960);
  vi.spyOn(HTMLCanvasElement.prototype, 'clientHeight', 'get').mockReturnValue(540);
  window.VellumUI = {};
  new Function(readFileSync(resolve(uploads, 'components/dvk-motion-shaders.js'), 'utf8'))();
  new Function(compiled)();
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function render(props = {}) {
  await act(async () => root.render(React.createElement(window.VellumUI.DvkMotionBackground, props)));
}
async function loadImages() {
  await act(async () => { images.forEach(image => image.onload?.()); });
}
function frame(time = 1000) {
  const [id, callback] = frames.entries().next().value;
  frames.delete(id);
  callback(time);
}

test.each(Object.keys(provenance))('%s preserves the original shaders and image assets byte for byte', name => {
  const digest = value => createHash('sha256').update(value).digest('hex');
  const shader = window.VellumUI.DvkMotionShaders[name];
  expect(digest(shader.vert)).toBe(provenance[name].vertexSha256);
  expect(digest(shader.frag)).toBe(provenance[name].fragmentSha256);
  if (provenance[name].glyphSha256) expect(digest(shader.glyph)).toBe(provenance[name].glyphSha256);
  for (const [file, hash] of Object.entries(provenance[name].assets)) {
    expect(digest(readFileSync(resolve(uploads, `assets/backgrounds/dvk/${name}/${file}`)))).toBe(hash);
  }
});

test('shows the supplied scene as fallback when WebGL is unavailable', async () => {
  HTMLCanvasElement.prototype.getContext.mockReturnValue(null);
  await render({variant:'dusk'});
  expect(container.firstChild.style.backgroundImage).toContain('dusk/scene.jpg');
  expect(container.firstChild.getAttribute('aria-hidden')).toBe('true');
  expect(container.querySelector('canvas').style.opacity).toBe('0');
  expect(frames.size).toBe(0);
});

test('draws one original shader frame at time zero under reduced motion', async () => {
  motion.matches = true;
  await render();
  await loadImages();
  frame();
  expect(gl.drawArrays).toHaveBeenCalledTimes(1);
  expect(gl.uniform1f.mock.calls.at(-1)[1]).toBe(0);
  expect(container.querySelector('canvas').style.opacity).toBe('1');
  expect(frames.size).toBe(0);
  resize();
  frame();
  expect(frames.size).toBe(0);
});

test('pauses the existing renderer while hidden, offscreen, or explicitly paused', async () => {
  await render();
  await loadImages();
  frame(1000);
  frame(2000);
  await render({paused:true});
  expect(frames.size).toBe(0);
  expect(gl.deleteProgram).not.toHaveBeenCalled();
  await render({paused:false});
  frame(10000);
  expect(gl.uniform1f.mock.calls.at(-1)[1]).toBe(1);
  intersection([{isIntersecting:false}]);
  expect(frames.size).toBe(0);
  intersection([{isIntersecting:true}]);
  expect(frames.size).toBe(1);
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  document.dispatchEvent(new Event('visibilitychange'));
  expect(frames.size).toBe(0);
});

test('Meadow waits for its original depth map before starting', async () => {
  await render({variant:'meadow'});
  expect(images.map(image => image.src)).toEqual(['assets/backgrounds/dvk/meadow/scene.jpg','assets/backgrounds/dvk/meadow/maps.png']);
  await act(async () => images[0].onload());
  expect(frames.size).toBe(0);
  await act(async () => images[1].onload());
  frame();
  expect(gl.texImage2D).toHaveBeenCalledTimes(2);
  expect(gl.drawArrays).toHaveBeenCalledTimes(1);
});

test.each(['grotto','evergreen','sunset-ridge'])('%s waits for every required original texture', async variant => {
  await render({variant});
  const files = variant === 'sunset-ridge' ? ['scene.jpg','maps.png','sky.jpg'] : ['scene.jpg','maps.png'];
  expect(images.map(image => image.src)).toEqual(files.map(file => `assets/backgrounds/dvk/${variant}/${file}`));
  await act(async () => images.slice(0,-1).forEach(image => image.onload()));
  expect(frames.size).toBe(0);
  await act(async () => images.at(-1).onload());
  frame();
  expect(gl.drawArrays).toHaveBeenCalledTimes(1);
});

test('Sunset Ridge previews use its original small sky plate', async () => {
  await render({variant:'sunset-ridge',preview:true});
  expect(images.map(image => image.src)).toEqual(['scene_s.jpg','maps.png','sky_s.jpg'].map(file => 'assets/backgrounds/dvk/sunset-ridge/'+file));
});

test.each([['cloudline',.5],['seascape',.7]])('%s preserves its WebGL1 render scale and reduced-motion time', async (variant, scale) => {
  motion.matches = true;
  vi.stubGlobal('devicePixelRatio', 2);
  await render({variant});
  expect(HTMLCanvasElement.prototype.getContext).toHaveBeenCalledWith('webgl', {antialias:false,alpha:false});
  expect(images).toHaveLength(0);
  expect(container.querySelector('canvas').width).toBe(Math.floor(960*scale));
  frame();
  expect(gl.uniform1f.mock.calls.at(-1)[1]).toBe(20);
  expect(frames.size).toBe(0);
});

test('Orbit ASCII uses the original glyph atlas and both render passes, then releases its framebuffer', async () => {
  motion.matches = true;
  await render({variant:'orbit-ascii'});
  expect(images.map(image => image.src)).toEqual(['assets/backgrounds/dvk/orbit-ascii/glyphs.png']);
  expect(frames.size).toBe(0);
  await loadImages();
  frame();
  expect(gl.drawArrays).toHaveBeenCalledTimes(2);
  expect(gl.pixelStorei).toHaveBeenCalledWith('UNPACK_FLIP_Y_WEBGL',false);
  expect(gl.uniform1f.mock.calls.some(([,value]) => value === 27)).toBe(true);
  expect(gl.uniform1f.mock.calls.some(([,value]) => value === 12)).toBe(true);
  expect(frames.size).toBe(0);
  await act(async () => root.render(null));
  expect(gl.deleteFramebuffer).toHaveBeenCalledTimes(1);
  expect(gl.deleteProgram).toHaveBeenCalledTimes(2);
  expect(gl.deleteShader).toHaveBeenCalledTimes(4);
});

test('Orbit ASCII keeps its source fallback without rendering when the glyph atlas fails', async () => {
  await render({variant:'orbit-ascii'});
  await act(async () => images[0].onerror());
  expect(frames.size).toBe(0);
  expect(container.querySelector('canvas').style.opacity).toBe('0');
});

test('a missing Meadow depth map keeps the original still scene usable', async () => {
  await render({variant:'meadow'});
  await act(async () => { images[0].onload(); images[1].onerror(); });
  expect(frames.size).toBe(0);
  expect(container.querySelector('canvas').style.opacity).toBe('0');
});

test('switching scenes releases textures, programs, shaders, frames, and late image callbacks', async () => {
  await render({variant:'meadow'});
  await loadImages();
  frame();
  const oldCanvas = container.querySelector('canvas');
  await render({variant:'eclipse'});
  expect(container.querySelector('canvas')).not.toBe(oldCanvas);
  expect(gl.deleteTexture).toHaveBeenCalledTimes(2);
  expect(gl.deleteShader).toHaveBeenCalledTimes(2);
  expect(gl.deleteBuffer).toHaveBeenCalledTimes(1);
  expect(gl.deleteProgram).toHaveBeenCalledTimes(1);
  expect(lostContext).toHaveBeenCalledTimes(1);
  const lateImage = images.at(-1).onload;
  await act(async () => root.render(null));
  await act(async () => lateImage());
  expect(frames.size).toBe(0);
  expect(images.at(-1).onload).toBeNull();
  expect(container.querySelector('canvas')).toBeNull();
});

test('previews load the original small scene and reduced source resolution', async () => {
  vi.stubGlobal('devicePixelRatio', 1);
  await render({variant:'stratosphere',preview:true});
  expect(images[0].src).toBe('assets/backgrounds/dvk/stratosphere/scene_s.jpg');
  expect(container.firstChild.style.backgroundImage).toContain('stratosphere/scene_s.jpg');
  expect(container.querySelector('canvas').width).toBe(384);
});

test('shader failure and context loss return to the still scene without a render loop', async () => {
  gl.getShaderParameter.mockReturnValue(false);
  await render();
  expect(lostContext).toHaveBeenCalledTimes(1);
  expect(frames.size).toBe(0);
  gl.getShaderParameter.mockReturnValue(true);
  await render({variant:'daybreak'});
  await loadImages();
  frame();
  container.querySelector('canvas').dispatchEvent(new Event('webglcontextlost', {cancelable:true}));
  expect(container.querySelector('canvas').style.opacity).toBe('0');
  expect(frames.size).toBe(0);
});
