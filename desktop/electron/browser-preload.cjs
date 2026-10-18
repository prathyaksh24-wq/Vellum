const {ipcRenderer} = require('electron');
// The guest gets no exposed native API. Only this isolated preload receives cursor updates.
let host, shape, custom;
function pointer(data) {
  if (!data) { host?.remove();host=null;return; }
  if (!host) {
    host=document.createElement('div');
    host.setAttribute('data-vellum-agent-cursor','');
    const shadow=host.attachShadow({mode:'closed'});
    shape=document.createElementNS('http://www.w3.org/2000/svg','svg');
    shape.setAttribute('viewBox','0 0 32 32');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d','M3 2 L3 25 L10 19 L15 29 L20 27 L15 17 L25 16 Z');
    path.setAttribute('stroke','#171717');path.setAttribute('stroke-width','1.5');
    shape.append(path);shadow.append(shape);
    custom=document.createElement('img');shadow.append(custom);
    custom.onerror=()=>{custom.style.display='none';shape.style.display='block';};
    Object.assign(host.style,{position:'fixed',pointerEvents:'none',zIndex:'2147483647',left:'0',top:'0',display:'block',filter:'drop-shadow(0 2px 2px #0005)'});
  }
  const settings=data.preferences || {};
  const size=Math.max(16,Math.min(48,settings.cursor_size || 28));
  const colors={classic:['#20252b','#ffffff'],light:['#ffffff','#20252b'],ember:['#ff8655','#332016'],mint:['#7ce8bd','#12372c'],pixel:['#fff5cf','#252525']};
  const [fill,stroke]=colors[settings.cursor_style] || colors.classic;
  shape.firstChild.setAttribute('fill',fill);shape.firstChild.setAttribute('stroke',stroke);
  shape.firstChild.setAttribute('d',settings.cursor_style==='pixel' ? 'M3 2h4v4h4v4h4v4h4v4h-8v4H7v-8H3Z' : 'M3 2 24 18l-10 1-5 9Z');
  shape.setAttribute('width',size);shape.setAttribute('height',size);
  const png=settings.cursor_style==='custom' && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(settings.cursor_image || '');
  shape.style.display=png ? 'none' : 'block';custom.style.display=png ? 'block' : 'none';
  if(png){custom.src=settings.cursor_image;custom.width=size;custom.height=size;}
  host.style.transform=`translate(${data.x-(png ? settings.cursor_hotspot_x || 0 : size*3/32)}px,${data.y-(png ? settings.cursor_hotspot_y || 0 : size*2/32)}px)`;
  const parent=document.fullscreenElement || document.documentElement;
  if (parent && host.parentNode!==parent) parent.append(host);
}
ipcRenderer.on('vellum:browser-pointer', (_event,data)=>pointer(data));
window.addEventListener('keydown',event=>{
  if(event.key==='Escape' && document.fullscreenElement) {
    event.preventDefault();event.stopImmediatePropagation();
    document.exitFullscreen().catch(()=>{});
  }
},true);
for (const event of ['pointerdown','wheel','keydown']) {
  window.addEventListener(event, input=>{if (input.isTrusted) ipcRenderer.send('vellum:browser-human-input');},{capture:true,passive:true});
}
