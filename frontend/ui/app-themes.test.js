import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';

const base='../design/Velllum/uploads/components/';
const require=createRequire(import.meta.url);
function compile(source) {
  const original=globalThis.Uint8Array;
  try {
    globalThis.Uint8Array=new TextEncoder().encode('').constructor;
    return createRequire(require.resolve('vite'))('esbuild').transformSync(source,{loader:'jsx'}).code;
  } finally { globalThis.Uint8Array=original; }
}
let themes,root,host;
beforeEach(()=>{
  globalThis.IS_REACT_ACT_ENVIRONMENT=true;
  localStorage.clear();document.documentElement.removeAttribute('style');
  window.VellumUI={};
  Function(readFileSync(base+'app-theme-presets.js','utf8'))();
  Function(readFileSync(base+'app-themes.js','utf8'))();
  themes=window.VellumUI.AppThemes;
});
afterEach(async()=>{
  if(root)await act(async()=>root.unmount());
  root=null;host?.remove();host=null;
  vi.restoreAllMocks();document.documentElement.removeAttribute('style');
});

test('all ten requested themes have distinct source identities and both mode palettes',()=>{
  expect(themes.presets).toHaveLength(10);
  expect(new Set(themes.presets.map(preset=>preset.id)).size).toBe(10);
  expect(new Set(themes.presets.map(preset=>JSON.stringify([preset.light,preset.dark]))).size).toBe(10);
  for(const preset of themes.presets)for(const mode of ['light','dark']) {
    expect(preset.source).toMatch(/^https:\/\/21st.dev\/@/);
    for(const token of ['background','foreground','primary','card','border'])expect(preset[mode][token]).toMatch(/^#[0-9a-f]{6}$/i);
  }
});

function mix(color,other,opacity) {
  const channels=[1,3,5].map(index=>Math.round(parseInt(color.slice(index,index+2),16)*(1-opacity)+other*opacity));
  return '#'+channels.map(value=>value.toString(16).padStart(2,'0')).join('');
}
test('plain named themes keep readable text across every theme and mode',()=>{
  for(const preset of themes.presets)for(const mode of ['light','dark']) {
    themes.reset();themes.apply({[mode+'_theme']:preset.id,background_opacity:1},mode);
    const style=document.documentElement.style;
    const surface=style.getPropertyValue('--bg');
    const opacity=Number(style.getPropertyValue('--app-background-opacity'));
    for(const token of ['--txt','--dim'])for(const extreme of [0,255]) {
      const ratio=themes.contrast(style.getPropertyValue(token),mix(surface,extreme,opacity));
      expect(ratio,`${preset.id} ${mode} ${token} against ${extreme}`).toBeGreaterThanOrEqual(4.5);
    }
    for(const token of ['--txt','--dim'])for(const panel of ['--panel','--glass-side','--menu-solid','--input','--code-bg']) {
      expect(themes.contrast(style.getPropertyValue(token),style.getPropertyValue(panel)),`${preset.id} ${mode} ${token} on ${panel}`).toBeGreaterThanOrEqual(4.5);
    }
    expect(themes.contrast(style.getPropertyValue('--onember'),style.getPropertyValue('--ember'))).toBeGreaterThanOrEqual(4.5);
    expect(opacity).toBe(0);
  }
});

test('legacy background palettes gain contrast protection and profiles do not leak stale theme tokens',()=>{
  themes.apply({dark_theme:'quantum-rose'},'dark');
  expect(document.documentElement.style.getPropertyValue('--danger')).not.toBe('');
  themes.reset();document.documentElement.style.setProperty('--bg','#79a9ee');
  themes.apply({},'light',{base:'#79a9ee',foreground:'#263a57',foregroundStrong:'#101d31',muted:'#506887'});
  expect(document.documentElement.dataset.appTheme).toBe('default');
  expect(document.documentElement.style.getPropertyValue('--bg')).toBe('#79a9ee');
  expect(document.documentElement.style.getPropertyValue('--danger')).toBe('');
  expect(themes.contrast(document.documentElement.style.getPropertyValue('--dim'),'#79a9ee')).toBeGreaterThanOrEqual(4.5);
});

test('backgrounds retain full brightness despite previously saved visibility settings',()=>{
  for(const mode of ['light','dark'])for(const background_opacity of [0,0.4,1]) {
    themes.reset();themes.apply({background_opacity},mode,{base:'#102824',foreground:'#eeeeee',muted:'#aabbcc'});
    expect(document.documentElement.style.getPropertyValue('--app-background-opacity')).toBe('1');
  }
});

test('a light background cannot overwrite the selected app theme palette',()=>{
  const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
  const source=html.slice(html.indexOf('const BACKGROUND_THEME_PROPS ='),html.indexOf('const AmbientBackground ='));
  const applyBackground=new Function('ACCENTS','accentOn',source+'\nreturn applyBackgroundTheme;')([],()=> '#ffffff');
  const entry={theme:{tone:'light',base:'#ffffff',surfaceRgb:'255,255,255',foreground:'#222222',foregroundStrong:'#000000',muted:'#666666',faint:'#777777',accent:'#4477aa',accent2:'#224466',textShadow:'none'}};
  Object.defineProperty(entry,'theme',{get(){throw Error('Named themes must not derive a background palette');}});
  applyBackground(entry,'dark',{dark_theme:'catppuccin',background_opacity:1});
  expect(document.documentElement.style.getPropertyValue('--bg')).toBe('#181825');
  expect(document.documentElement.dataset.appTheme).toBe('catppuccin');
  applyBackground(entry,'light',{light_theme:'zen-linen'});
  expect(document.documentElement.style.getPropertyValue('--bg')).toBe('#E9E4D8');
});

test('one saved theme uses matching light and dark variants after reload',()=>{
  Function(readFileSync(base+'app-action-runtime.js','utf8'))();
  const adapter=window.VellumUI.AppActions.createDeviceSettingsRuntime({storage:localStorage,client:{}});
  adapter.applyReceipt({status:'applied',result:{device_settings_patch:{version:1,base_revision:0,revision:1,values:{appearance:{dark_theme:'catppuccin',light_theme:'catppuccin'},background:'drifting-clouds'}}}});
  const reloaded=window.VellumUI.AppActions.createDeviceSettingsRuntime({storage:localStorage,client:{}}).snapshot();
  for(const mode of ['light','dark'])expect(themes.resolve(reloaded.values.appearance,mode).preset.id).toBe('catppuccin');
  expect(themes.resolve(reloaded.values.appearance,'light').tokens.background).not.toBe(themes.resolve(reloaded.values.appearance,'dark').tokens.background);
  expect(themes.resolve({light_theme:'zen-linen',dark_theme:'catppuccin'},'light').preset.id).toBe('catppuccin');
});

test('named themes unmount the background and release its animation lifecycle',async()=>{
  const html=readFileSync('../design/Velllum/uploads/Vellum Default Re-designed.html','utf8');
  const source=html.slice(html.indexOf('const AppBackground ='),html.indexOf('const BackgroundChoiceCard ='));
  const Context=React.createContext(null),unmounted=vi.fn(),mounted=vi.fn();
  function Renderer(){React.useEffect(()=>{mounted();return unmounted;},[]);return React.createElement('canvas');}
  const AppBackground=Function('React','useBackground','BackgroundRenderer',compile(source+'\nwindow.TestAppBackground=AppBackground;')+'\nreturn window.TestAppBackground;')(React,()=>React.useContext(Context),Renderer);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  const render=async(profile)=>act(async()=>root.render(React.createElement(Context.Provider,{value:{background:{id:'ember-clouds'},backgroundVisibility:0,themeProfile:profile}},React.createElement(AppBackground))));
  await render(null);expect(host.querySelector('canvas')).not.toBeNull();
  await render(themes.resolve({dark_theme:'catppuccin'},'dark'));
  expect(host.querySelector('.app-background')).toBeNull();expect(unmounted).toHaveBeenCalledTimes(1);
  await render(themes.resolve({dark_theme:'catppuccin'},'light'));
  expect(host.querySelector('canvas')).toBeNull();expect(mounted).toHaveBeenCalledTimes(1);
  await render(null);expect(host.querySelector('canvas')).not.toBeNull();expect(mounted).toHaveBeenCalledTimes(2);
});

test('rapid device changes are serialized with the latest receipt revision and recover after rejection',async()=>{
  Function(readFileSync(base+'app-action-runtime.js','utf8'))();
  let revision=0;
  const client={dispatch:vi.fn(async(request,context)=>{
    expect(context.device_settings.revision).toBe(revision);
    if(request.arguments.patch.accent==='invalid')throw Error('failed');
    return {status:'applied',result:{device_settings_patch:{version:1,base_revision:revision,revision:++revision,values:request.arguments.patch}}};
  })};
  const adapter=window.VellumUI.AppActions.createDeviceSettingsRuntime({storage:localStorage,client});
  await Promise.all([adapter.dispatch({appearance:{dark_theme:'catppuccin'}}),adapter.dispatch({appearance:{light_theme:'sage-garden'}})]);
  await expect(adapter.dispatch({accent:'invalid'})).rejects.toThrow('failed');
  await adapter.dispatch({background:'galaxy'});
  expect(adapter.snapshot()).toMatchObject({revision:3,values:{appearance:{dark_theme:'catppuccin',light_theme:'sage-garden'}}});
});

test('theme options mount in the real shared selector with their color previews',async()=>{
  window.VellumUI.AppIcon=()=>React.createElement('svg');
  Function('React',compile(readFileSync(base+'v-select.jsx','utf8')))(React);
  Function('React',compile(readFileSync(base+'app-theme-settings.jsx','utf8')))(React);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(React.createElement(window.VellumUI.AppThemeSettings,{appearance:{dark_theme:'catppuccin',light_theme:'zen-linen'},mode:'dark',onDeviceSettings:vi.fn()})));
  expect(host.querySelectorAll('[role="combobox"]')).toHaveLength(1);
  expect(host.querySelector('[aria-label="App theme"][role="combobox"]').textContent).toContain('Catppuccin');
  expect(host.querySelectorAll('img[src^="data:image/svg+xml,"]').length).toBeGreaterThan(10);
  expect(host.querySelector('[aria-label="Background visibility"]')).toBeNull();
});

test('failed selection keeps the saved profile and exposes a recovery error',async()=>{
  window.VellumUI.VSelect=props=>React.createElement('select',{'aria-label':props.ariaLabel,value:props.value,disabled:props.disabled,onChange:event=>props.onValueChange(event.target.value)},props.options.map(option=>React.createElement('option',{key:option.value,value:option.value},option.label)));
  Function('React',compile(readFileSync(base+'app-theme-settings.jsx','utf8')))(React);
  const save=vi.fn(async()=>({status:'failed',message:'Theme could not be saved'}));
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(React.createElement(window.VellumUI.AppThemeSettings,{appearance:{dark_theme:'catppuccin'},mode:'dark',onDeviceSettings:save})));
  const picker=host.querySelector('[aria-label="App theme"]');
  await act(async()=>{picker.value='quantum-rose';picker.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(save).toHaveBeenCalledExactlyOnceWith({appearance:{light_theme:'quantum-rose',dark_theme:'quantum-rose'}});
  expect(picker.value).toBe('catppuccin');expect(picker.disabled).toBe(false);
  expect(host.querySelector('[role="alert"]').textContent).toContain('Theme could not be saved');
});
