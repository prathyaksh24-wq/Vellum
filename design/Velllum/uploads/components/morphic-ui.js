/* Motion adapted from the supplied Agent composer.html. Presentation only. */
(function () {
  const h=(...args)=>window.React.createElement(...args);
  function SharedRowBackground({children,className='',activeSelector='[aria-selected="true"]',refreshKey,role,label,id,onKeyDown,onMouseLeave}) {
    const ref=window.React.useRef(null),pill=window.React.useRef(null),hovered=window.React.useRef(null);
    const measure=window.React.useCallback(row=>{
      const box=ref.current,bg=pill.current;if(!box || !bg)return;
      if(!row || !box.contains(row)){bg.style.opacity='0';return;}
      // The source's local offset geometry lets the highlight scroll with rows.
      bg.style.width=row.offsetWidth+'px';bg.style.height=row.offsetHeight+'px';
      bg.style.transform=`translate(${row.offsetLeft}px,${row.offsetTop}px)`;bg.style.opacity='1';
    },[]);
    window.React.useLayoutEffect(()=>{
      const box=ref.current,row=box?.querySelector(activeSelector);
      hovered.current=null;
      if(row && box.scrollHeight>box.clientHeight){
        const top=row.offsetTop,bottom=top+row.offsetHeight;
        if(top<box.scrollTop)box.scrollTop=top;
        else if(bottom>box.scrollTop+box.clientHeight)box.scrollTop=bottom-box.clientHeight;
      }
      measure(row);
    },[activeSelector,refreshKey,measure]);
    window.React.useEffect(()=>{
      const box=ref.current;if(!box || typeof ResizeObserver!=='function')return;
      const observer=new ResizeObserver(()=>measure(hovered.current?.isConnected?hovered.current:box.querySelector(activeSelector)));
      observer.observe(box);return()=>observer.disconnect();
    },[activeSelector,measure]);
    return h('div',{ref,id,role,'aria-label':label,'data-shared-layout-group':'',className:'morphic-group '+className,onKeyDown,
      onPointerOver:event=>{if(event.pointerType==='touch')return;const row=event.target.closest('[data-shared-row]');if(row && row.closest('[data-shared-layout-group]')===ref.current){hovered.current=row;measure(row);}},
      onPointerLeave:()=>{hovered.current=null;measure(ref.current?.querySelector(activeSelector));onMouseLeave?.();},
      onFocus:event=>{const row=event.target.closest('[data-shared-row]');if(row)measure(row);}},
      h('i',{ref:pill,className:'hlb','aria-hidden':true}),children);
  }

  function MorphicTooltip() {
    window.React.useEffect(()=>{
      const panel=document.createElement('div');panel.id='vellum-morphic-tooltip';panel.className='morphic-tooltip nt';panel.role='tooltip';
      panel.setAttribute('aria-hidden','true');panel.setAttribute('popover','manual');document.body.append(panel);
      let current=null,hideTimer=0,frame=0,shown=false,lastText='',lastKey='',savedTitle=null;
      const media=window.matchMedia('(prefers-reduced-motion: reduce)');
      const titles=new WeakMap();
      const eligible=target=>{
        if(!(target instanceof Element))return null;
        const el=target.closest('[data-tip],[data-tooltip]');
        if(!el || el.closest('[inert],[aria-hidden="true"],[data-morphic-tooltip="off"],[data-slot="tooltip-trigger"]'))return null;
        const described=(el.getAttribute('aria-describedby') || '').split(/\s+/);
        if(described.some(id=>id!==panel.id && document.getElementById(id)?.getAttribute('role')==='tooltip'))return null;
        return el;
      };
      const label=el=>el.getAttribute('data-tip') || el.getAttribute('data-tooltip') || el.getAttribute('title') || titles.get(el) || el.getAttribute('aria-label') || '';
      const unlink=()=>{
        if(!current)return;
        const ids=(current.getAttribute('aria-describedby') || '').split(/\s+/).filter(id=>id && id!==panel.id);
        if(ids.length)current.setAttribute('aria-describedby',ids.join(' '));else current.removeAttribute('aria-describedby');
        if(savedTitle!==null && !current.hasAttribute('title'))current.setAttribute('title',savedTitle);
        current.removeAttribute('data-morphic-title');
        savedTitle=null;
      };
      const hide=(immediate=false)=>{
        clearTimeout(hideTimer);
        const end=()=>{shown=false;panel.style.opacity='0';panel.setAttribute('aria-hidden','true');unlink();current=null;resize?.disconnect();
          if(immediate){if(panel.matches(':popover-open'))panel.hidePopover();}
          else hideTimer=setTimeout(()=>{if(!shown && panel.matches(':popover-open'))panel.hidePopover();},150);
        };
        if(immediate)end();else hideTimer=setTimeout(end,140);
      };
      const position=()=>{
        if(!current?.isConnected){hide(true);return;}
        const rect=current.getBoundingClientRect();if(!rect.width || !rect.height){hide(true);return;}
        const copy=panel.firstElementChild;if(!copy)return;
        const width=Math.min(copy.offsetWidth,innerWidth-16),height=copy.offsetHeight;
        const x=Math.max(8,Math.min(innerWidth-width-8,rect.left+rect.width/2-width/2));
        let left=x,y=rect.top-height-10;
        const side=current.getAttribute('data-tooltip-side');
        if(side==='bottom')y=rect.bottom+10;
        else if(side==='left' || side==='right'){
          left=side==='left'?rect.left-width-10:rect.right+10;y=rect.top+(rect.height-height)/2;
          if(left<8 || left+width>innerWidth-8){left=x;y=rect.top-height-10;}
        }
        if(y<8)y=rect.bottom+10;y=Math.max(8,Math.min(innerHeight-height-8,y));
        panel.style.width=width+'px';panel.style.height=height+'px';panel.style.transform=`translate(${left}px,${y}px)`;
      };
      const resize=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(shown)position();}):null;
      const show=el=>{
        const text=label(el);if(!text)return;clearTimeout(hideTimer);
        const key=el.getAttribute('data-k') || el.getAttribute('aria-keyshortcuts') || '';
        if(current===el && shown && text===lastText && key===lastKey)return;
        const first=!shown;
        unlink();current=el;lastText=text;lastKey=key;
        // The tooltip lives in the top layer; inherit the active surface palette.
        const palette=getComputedStyle(el);
        for(const token of ['--menu-solid','--txt2','--hover2']){
          const value=palette.getPropertyValue(token).trim();
          if(value)panel.style.setProperty(token,value);else panel.style.removeProperty(token);
        }
        savedTitle=el.hasAttribute('title')?el.getAttribute('title'):null;
        if(savedTitle!==null){titles.set(el,savedTitle);el.setAttribute('data-morphic-title',savedTitle);el.removeAttribute('title');}
        const copy=document.createElement('div');copy.className='morphic-tooltip-copy';
        const span=document.createElement('span');span.textContent=text;copy.append(span);
        if(key){const shortcut=document.createElement('kbd');shortcut.textContent=key;copy.append(shortcut);}
        panel.replaceChildren(copy);panel.classList.toggle('nt',first || media.matches);
        if(panel.showPopover && !panel.matches(':popover-open'))panel.showPopover();
        panel.setAttribute('aria-hidden','false');
        position();shown=true;
        const ids=(el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);el.setAttribute('aria-describedby',[...new Set([...ids,panel.id])].join(' '));
        resize?.disconnect();resize?.observe(el);
        cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(shown)panel.style.opacity='1';});
      };
      const over=event=>{if(event.pointerType==='touch')return;const el=eligible(event.target);if(el)show(el);else if(current)hide();};
      const out=event=>{const next=eligible(event.relatedTarget);if(next===current)return;if(next)show(next);else if(current)hide();};
      const focus=event=>{const el=eligible(event.target);if(el && event.target.matches(':focus-visible'))show(el);};
      const blur=event=>{if(!current?.contains(event.relatedTarget))hide();};
      const dismiss=()=>hide(true);
      const keydown=event=>{if(event.key==='Escape')dismiss();};
      const viewport=()=>{if(shown){cancelAnimationFrame(frame);frame=requestAnimationFrame(position);}};
      const visibility=()=>{if(document.hidden)dismiss();};
      document.addEventListener('pointerover',over);document.addEventListener('pointerout',out);
      document.addEventListener('focusin',focus);document.addEventListener('focusout',blur);
      document.addEventListener('pointerdown',dismiss,true);document.addEventListener('keydown',keydown);
      document.addEventListener('visibilitychange',visibility);window.addEventListener('blur',dismiss);
      window.addEventListener('resize',viewport);window.addEventListener('scroll',viewport,true);
      media.addEventListener('change',dismiss);
      return()=>{
        clearTimeout(hideTimer);cancelAnimationFrame(frame);resize?.disconnect();unlink();panel.remove();
        document.removeEventListener('pointerover',over);document.removeEventListener('pointerout',out);
        document.removeEventListener('focusin',focus);document.removeEventListener('focusout',blur);
        document.removeEventListener('pointerdown',dismiss,true);document.removeEventListener('keydown',keydown);
        document.removeEventListener('visibilitychange',visibility);window.removeEventListener('blur',dismiss);
        window.removeEventListener('resize',viewport);window.removeEventListener('scroll',viewport,true);media.removeEventListener('change',dismiss);
      };
    },[]);
    return null;
  }
  window.VellumUI={...window.VellumUI,SharedRowBackground,MorphicTooltip};
})();
