/* App palettes are projections of the revisioned device appearance settings.
 * Backgrounds retain their own selection and animation lifecycle. */
(function () {
  const ui = window.VellumUI = window.VellumUI || {};
  const presets = ui.appThemePresets || [];
  const defaults = {light_theme:'default', dark_theme:'default', background_opacity:0.4};
  const ownedProperties = new Set();

  function rgb(color) {
    const value = String(color).replace('#','');
    const full = value.length === 3 ? value.split('').map(part=>part+part).join('') : value;
    return [0,2,4].map(offset=>parseInt(full.slice(offset,offset+2),16));
  }
  function hex(channels) {
    return '#'+channels.map(value=>Math.round(value).toString(16).padStart(2,'0')).join('');
  }
  function mix(first,second,weight) {
    const a=rgb(first), b=rgb(second);
    return hex(a.map((value,index)=>value*(1-weight)+b[index]*weight));
  }
  function luminance(color) {
    const channels=rgb(color).map(value=>{
      const channel=value/255;
      return channel<=0.04045?channel/12.92:Math.pow((channel+0.055)/1.055,2.4);
    });
    return channels[0]*0.2126+channels[1]*0.7152+channels[2]*0.0722;
  }
  function contrast(first,second) {
    const a=luminance(first), b=luminance(second);
    return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
  }
  function readable(color,surface,minimum=4.5) {
    if(contrast(color,surface)>=minimum)return color;
    const target=contrast('#000000',surface)>contrast('#ffffff',surface)?'#000000':'#ffffff';
    for(let step=1;step<=20;step++) {
      const candidate=mix(color,target,step/20);
      if(contrast(candidate,surface)>=minimum)return candidate;
    }
    return target;
  }
  function rgba(color,alpha) { return `rgba(${rgb(color).join(',')},${alpha})`; }
  function normalize(value) {
    const result={...defaults,...value};
    for(const mode of ['light','dark']) {
      const key=mode+'_theme';
      if(!presets.some(preset=>preset.id===result[key]))result[key]='default';
    }
    // Keep the existing persisted fields compatible, with one selected theme.
    const selected=result.dark_theme!=='default'?result.dark_theme:result.light_theme;
    result.light_theme=selected;
    result.dark_theme=selected;
    if(typeof result.background_opacity!=='number'||!Number.isFinite(result.background_opacity))result.background_opacity=defaults.background_opacity;
    result.background_opacity=Math.max(0,Math.min(1,result.background_opacity));
    return result;
  }
  function saved() {
    try { return normalize(JSON.parse(localStorage.getItem('vellum-device-settings-v1')||'{}').values?.appearance); }
    catch { return {...defaults}; }
  }
  function resolve(appearance,mode) {
    const settings=appearance?normalize(appearance):saved();
    const preset=presets.find(item=>item.id===settings[mode+'_theme']);
    return preset?{preset,tokens:preset[mode]}:null;
  }
  function reset(root=document.documentElement) {
    for(const property of ownedProperties)root.style.removeProperty(property);
    ownedProperties.clear();
  }
  function apply(appearance,mode='dark',legacyPalette,root=document.documentElement) {
    const settings=appearance?normalize(appearance):saved();
    const profile=resolve(settings,mode);
    const variables={};
    let surface=legacyPalette?.base || (mode==='light'?'#f2f0f0':'#0a0908');
    let foreground=legacyPalette?.foreground || (mode==='light'?'#2b2727':'#d1d0d0');
    foreground=readable(foreground,surface,7);
    let secondary=readable(legacyPalette?.muted||foreground,surface,7);
    if(profile) {
      const p=profile.tokens;
      surface=p.background;
      foreground=readable(p.foreground,surface,7);
      const card=p.card||surface, sidebar=p.sidebar||card, popover=p.popover||card;
      const accent=p.primary;
      const surfaces=[card,sidebar,popover,p.input||card,p.muted||card,surface];
      for(const background of surfaces)foreground=readable(foreground,background,7);
      const muted=surfaces.reduce((ink,background)=>readable(ink,background,7),p['muted-foreground']||foreground);
      secondary=muted;
      const onAccent=readable(p['primary-foreground']||foreground,accent);
      for(const [name,value] of Object.entries(p)) {
        if(!name.startsWith('font-'))variables['--app-'+name]=value;
      }
      Object.assign(variables,{
        '--bg':surface, '--stage':surface, '--panel':card, '--tb':sidebar,
        'color-scheme':luminance(surface)>0.5?'light':'dark',
        '--txt':foreground, '--txt2':foreground, '--dim':muted, '--dim2':muted,
        '--line':p.border, '--line2':p.border, '--winborder':p.border,
        '--ember':accent, '--accent2':p.ring||accent, '--onember':onAccent,
        '--grad':`linear-gradient(135deg,${accent},${p['chart-2']||accent})`,
        '--hover':rgba(accent,0.10), '--active':rgba(accent,0.18),
        '--bubble':card, '--modal':popover, '--input':p.input||card,
        '--glass':card, '--glass-win':'transparent', '--glass-bar':sidebar,
        '--glass-side':sidebar, '--menu-solid':popover,
        '--danger':readable(p.destructive,card), '--scroll':rgba(foreground,0.3),
        '--glow':rgba(accent,0.30), '--glow-soft':rgba(accent,0.12),
        '--accent-faded':p['chart-2']||accent, '--accent-deep':p.ring||accent, '--accent-bg':surface,
        '--background-text-shadow':'none', '--background-surface-shadow':'none',
        '--ascii-color':foreground, '--ascii-bg':surface,
        '--ui-control-radius':p.radius||'8px', '--ui-panel-radius':`calc(${p.radius||'8px'} + 4px)`,
        '--theme-focus':p.ring||accent, '--code-bg':p.muted, '--code-ink':foreground,
        '--diff-added':p['chart-3']||accent, '--diff-removed':p.destructive,
      });
      for(let index=1;index<=5;index++)variables['--color-'+index]=p['chart-'+index]||accent;
      root.dataset.backgroundTone=luminance(surface)>0.5?'light':'dark';
    }
    if(!profile)Object.assign(variables,{'--txt':readable(foreground,surface,7),'--txt2':readable(legacyPalette?.foregroundStrong||foreground,surface,7),'--dim':secondary,'--dim2':secondary});
    root.dataset.appTheme=profile?.preset.id||'default';
    // Scenes retain their original pixels. Legacy visibility settings are ignored.
    variables['--app-background-opacity']=profile?'0':'1';
    for(const [name,value] of Object.entries(variables)) {
      root.style.setProperty(name,value);
      ownedProperties.add(name);
    }
    window.dispatchEvent(new Event('vellum:appearance-change'));
    return profile;
  }
  function terminalTheme(element) {
    const style=getComputedStyle(element);
    const token=(name,fallback)=>style.getPropertyValue(name).trim()||fallback;
    return {
      background:token('--bg','#050505'), foreground:token('--txt','#f4f4f4'),
      cursor:token('--ember','#f4f4f4'), selectionBackground:token('--active','#444444'),
      red:token('--danger','#f08a8a'), green:token('--diff-added','#65b889'),
      yellow:token('--color-4','#d4b891'), blue:token('--color-2','#6d9fce'),
      magenta:token('--ember','#b996d3'), cyan:token('--color-3','#7ebcbe'),
    };
  }
  ui.AppThemes={presets,defaults,normalize,resolve,reset,apply,contrast,readable,terminalTheme};
})();
