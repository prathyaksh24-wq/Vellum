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
    bar.append(menus,feedback);
    document.body.prepend(bar);
    document.documentElement.classList.add('desktop-chrome-on');
    document.addEventListener('keydown',event=>{
      if(event.key==='F10'&&!event.shiftKey || event.altKey&&!event.ctrlKey&&!event.metaKey&&['v','e','w'].includes(event.key.toLowerCase())) {
        event.preventDefault();previousFocus=document.activeElement;
        const index=event.key==='F10'?0:({v:2,e:1,w:3})[event.key.toLowerCase()];
        focusButton(index);if(event.key!=='F10')buttons[index].click();
      }
    });
    const hex=(color,fallback)=>{
      const rgb=color.match(/^rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)/);
      return rgb?'#'+rgb.slice(1,4).map(value=>Number(value).toString(16).padStart(2,'0')).join(''):fallback;
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
