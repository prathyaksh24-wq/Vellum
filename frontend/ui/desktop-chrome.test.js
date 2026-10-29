import {readFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach,afterEach,expect,test,vi} from 'vitest';
const source=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../design/Velllum/uploads/components/desktop-chrome.js'),'utf8');
let openMenu,setTheme,listeners;
beforeEach(()=>{
  document.body.innerHTML='<input id="editor"><div id="root"></div>';
  openMenu=vi.fn(async()=>{});setTheme=vi.fn(async()=>{});
  window.VellumDesktop={chrome:{openMenu,setTheme}};
  listeners=[];
  const add=document.addEventListener.bind(document);
  vi.spyOn(document,'addEventListener').mockImplementation((type,fn,options)=>{listeners.push([type,fn]);add(type,fn,options);});
});
afterEach(()=>{
  for(const [type,fn]of listeners)document.removeEventListener(type,fn);
  document.documentElement.classList.remove('desktop-chrome-on');
  document.body.innerHTML='';delete window.VellumDesktop;vi.restoreAllMocks();
});
function mount(){new Function(source)();document.dispatchEvent(new Event('DOMContentLoaded'));}
test('browser pages keep their ordinary layout without the native chrome bridge',()=>{
  delete window.VellumDesktop;mount();expect(document.querySelector('header')).toBeNull();
});
test('desktop menus call only named native menus and support keyboard traversal',async()=>{
  mount();const buttons=[...document.querySelectorAll('[role="menuitem"]')];
  expect(buttons.map(x=>x.textContent)).toEqual(['Vellum','Edit','View','Window']);
  buttons[1].click();await Promise.resolve();
  expect(openMenu).toHaveBeenCalledWith('edit',0,0);
  buttons[1].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  expect(document.activeElement).toBe(buttons[2]);
  document.dispatchEvent(new KeyboardEvent('keydown',{key:'F10',bubbles:true}));
  expect(document.activeElement).toBe(buttons[0]);
  expect(setTheme).toHaveBeenCalled();
});
test('pointer menu activation preserves the focused editor and failures remain readable',async()=>{
  mount();const editor=document.querySelector('#editor');editor.focus();
  const button=document.querySelectorAll('[role="menuitem"]')[1];
  button.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));
  expect(document.activeElement).toBe(editor);
  openMenu.mockRejectedValueOnce(new Error('Unavailable'));
  button.click();await Promise.resolve();await Promise.resolve();
  expect(document.querySelector('[role="alert"]').textContent).toContain('could not open');
  expect(button.getAttribute('aria-expanded')).toBe('false');
});
