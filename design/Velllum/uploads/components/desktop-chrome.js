(function () {
  function mount() {
    const chrome=window.VellumDesktop?.chrome;
    if (!chrome || document.querySelector('.desktop-titlebar')) return;
    const bar=document.createElement('header');
    bar.className='desktop-titlebar';
    bar.setAttribute('aria-label','Vellum window');
    const menus=document.createElement('div');
    menus.className='desktop-menus';
    menus.setAttribute('role','menubar');
    menus.setAttribute('aria-label','Application menus');
    const feedback=document.createElement('span');
    feedback.className='desktop-menu-feedback';
    feedback.setAttribute('role','alert');
    const navigation=document.createElement('nav');
    navigation.className='desktop-navigation';
    navigation.setAttribute('aria-label','Vellum page history');
    const arrows=['Back','Forward'].map((label,index)=>{
      const button=document.createElement('button');
      button.type='button';button.disabled=true;
      button.setAttribute('aria-label',label);button.title=label+' (Alt+'+(index?'Right':'Left')+')';
      const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
      icon.setAttribute('width','16');icon.setAttribute('height','16');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('fill','currentColor');icon.setAttribute('aria-hidden','true');
      const glyph=document.createElementNS('http://www.w3.org/2000/svg','use');
      glyph.setAttribute('href',window.VellumUI.iconHref(index?'ArrowRight':'ArrowLeft'));icon.append(glyph);button.append(icon);
      button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('vellum:navigation-traverse',{detail:index?1:-1})));
      navigation.append(button);return button;
    });
    window.addEventListener('vellum:navigation-state',event=>{
      arrows[0].disabled=!event.detail?.back;arrows[1].disabled=!event.detail?.forward;
    });
    let opening=false;
    let previousFocus=null;
    const buttons=[];
    const focusButton=index=>{
      buttons.forEach((button,i)=>button.tabIndex=i===index?0:-1);
      buttons[index].focus();
    };
    for (const [index,label] of ['Vellum','Edit','View','Window'].entries()) {
      const button=document.createElement('button');
      button.type='button';button.textContent=label;button.tabIndex=index===0?0:-1;
      button.setAttribute('role','menuitem');button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');
      button.addEventListener('mousedown',event=>{previousFocus=document.activeElement;event.preventDefault();});
      button.addEventListener('click',async()=>{
        if (opening) return;
        const rect=button.getBoundingClientRect();
        opening=true;button.setAttribute('aria-expanded','true');feedback.textContent='';
        try {await chrome.openMenu(label.toLowerCase(),Math.round(rect.left),Math.round(rect.bottom));}
        catch {feedback.textContent='This menu could not open. Try again.';}
        finally {opening=false;button.setAttribute('aria-expanded','false');}
      });
      button.addEventListener('keydown',event=>{
        if (event.key==='ArrowRight'||event.key==='ArrowLeft') {
          event.preventDefault();focusButton((index+(event.key==='ArrowRight'?1:buttons.length-1))%buttons.length);
        } else if (event.key==='ArrowDown') {event.preventDefault();button.click();}
        else if (event.key==='Escape') {event.preventDefault();previousFocus?.isConnected && previousFocus.focus();}
      });
      menus.append(button);buttons.push(button);
    }
    bar.append(navigation,menus,feedback);
    document.body.prepend(bar);
    document.documentElement.classList.add('desktop-chrome-on');
    window.dispatchEvent(new Event('vellum:navigation-ready'));
    document.addEventListener('keydown',event=>{
      if(event.altKey&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&['ArrowLeft','ArrowRight'].includes(event.key)) {
        event.preventDefault();event.stopImmediatePropagation();arrows[event.key==='ArrowLeft'?0:1].click();return;
      }
      if(event.key==='F10'&&!event.shiftKey || event.altKey&&!event.ctrlKey&&!event.metaKey&&['v','e','w'].includes(event.key.toLowerCase())) {
        event.preventDefault();previousFocus=document.activeElement;
        const index=event.key==='F10'?0:({v:2,e:1,w:3})[event.key.toLowerCase()];
        focusButton(index);if(event.key!=='F10')buttons[index].click();
      }
    },true);
    const colorProbe=document.createElement('canvas').getContext('2d',{willReadFrequently:true});
    const hex=(color,fallback)=>{
      const rgb=color.match(/^rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)/);
      if(rgb)return '#'+rgb.slice(1,4).map(value=>Number(value).toString(16).padStart(2,'0')).join('');
      if(!colorProbe)return fallback;
      // Theme tokens may resolve to color(srgb ...) or relative CSS colors.
      // Normalize the actual computed color so native caption buttons match.
      colorProbe.clearRect(0,0,1,1);colorProbe.fillStyle=fallback;colorProbe.fillStyle=color;colorProbe.fillRect(0,0,1,1);
      return '#'+Array.from(colorProbe.getImageData(0,0,1,1).data).slice(0,3).map(value=>value.toString(16).padStart(2,'0')).join('');
    };
    function theme() {
      const style=getComputedStyle(bar);
      chrome.setTheme(hex(style.backgroundColor,'#151313'),hex(style.color,'#e8e2dc')).catch(()=>{});
    }
    new MutationObserver(theme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','style']});
    theme();
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
