/* Geometry and motion adapted from the user's Vellum face preview.html.
 * Uses the host React runtime and inherits the canonical device color. */
(() => {
  const {useEffect,useId,useRef,useState}=React;
  const DEFAULT_COLOR='#06a3ff';
  const ORANGE_COLOR='#f45434';
  const originalOrange={
    'rim':'#fff9f5',
    'body-2':'#fa7342',
    'body-3':'#ffb175',
    'eye':'#ffe8db',
    'eye-shade':'rgba(230, 90, 50, .3)',
    'halo':'rgba(240, 100, 60, .2)',
    'edge':'rgba(220, 80, 40, .4)',
    'shadow':'rgba(170, 50, 20, .5)',
  };
  const validColor=value=>/^#[0-9a-f]{6}$/i.test(value||'');
  function faceColorStyle(value) {
    const color=validColor(value)?value.toLowerCase():DEFAULT_COLOR;
    const style={'--vellum-face-color':color};
    for (const [part,orange] of Object.entries(originalOrange)) {
      style[`--vellum-face-${part}`]=color===ORANGE_COLOR?orange:'initial';
    }
    return style;
  }
  const circles=[{cx:115,cy:93,r:43},{cx:163,cy:111,r:39},{cx:156,cy:155,r:31},{cx:107,cy:155,r:35},{cx:72,cy:126,r:34}];
  const around=(x,y,transform)=>`translate(${x} ${y}) ${transform} translate(${-x} ${-y})`;
  function VellumFace({color,background=false,animated=true,interactive=true,icon=false,className='',label='Vellum cloud face'}) {
    const id='vf'+useId().replace(/[^a-zA-Z0-9_-]/g,''),url=name=>`url(#${id}-${name})`;
    const host=useRef(null),body=useRef(null),head=useRef(null),eyes=useRef(null),left=useRef(null),right=useRef(null),shine=useRef(null),shadow=useRef(null);
    useEffect(()=>{
      const node=host.current,motion=matchMedia('(prefers-reduced-motion: reduce)');
      let frame=0,last=0,time=0,visible=true,nextLook=1.2,nextBlink=1.8,blink=-1,wink=-1,double=false,pointer=false;
      const gaze={x:0,y:0,vx:0,vy:0},target={x:0,y:0},squish={p:0,v:0};
      const blinkScale=(elapsed,duration=.16)=>elapsed<0||elapsed>duration?1:1-.9*Math.sin(elapsed/duration*Math.PI);
      const paint=()=>{
        const still=motion.matches||!animated,float=still?0:Math.sin(time*1.1)*5,breath=still?0:Math.sin(time*1.1+Math.PI/2)*.012;
        body.current?.setAttribute('transform',`translate(0 ${float}) ${around(120,180,`scale(${1-breath+squish.p*.1} ${1+breath-squish.p*.12})`)}`);
        head.current?.setAttribute('transform',`translate(${gaze.x*4} ${gaze.y*2}) ${around(120,120,`rotate(${gaze.x*2.5}) scale(${1-Math.abs(gaze.x)*.025} 1)`)}`);
        eyes.current?.setAttribute('transform',`translate(${gaze.x*12} ${gaze.y*7})`);
        shine.current?.setAttribute('transform',`translate(${-gaze.x*7} ${-gaze.y*3})`);
        const scale=blink<0?1:Math.min(blinkScale(time-blink),double?blinkScale(time-blink-.26):1);
        left.current?.setAttribute('transform',around(105.5,121.5,`scale(1 ${scale})`));
        right.current?.setAttribute('transform',around(136.5,121.5,`scale(1 ${Math.min(scale,blinkScale(time-wink,.34))})`));
        const height=(float+5)/10;
        shadow.current?.setAttribute('transform',around(120,210,`scale(${1-height*.12} 1)`));
        shadow.current?.setAttribute('opacity',String(.34-height*.1));
      };
      const tick=now=>{
        const dt=Math.min(.05,(now-(last||now))/1000);last=now;time+=dt;
        if(!pointer&&time>nextLook){const looks=[[0,0],[-1,.05],[1,-.05],[0,0],[.65,-.55],[-.7,.35]],look=looks[Math.floor(Math.random()*looks.length)];target.x=look[0];target.y=look[1];nextLook=time+1.4+Math.random()*2.2;}
        if(time>nextBlink){blink=time;double=Math.random()<.25;nextBlink=time+2.4+Math.random()*3;}
        gaze.vx+=((target.x-gaze.x)*70-gaze.vx*13)*dt;gaze.vy+=((target.y-gaze.y)*70-gaze.vy*13)*dt;gaze.x+=gaze.vx*dt;gaze.y+=gaze.vy*dt;
        squish.v+=(-squish.p*220-squish.v*9)*dt;squish.p+=squish.v*dt;paint();frame=requestAnimationFrame(tick);
      };
      const stop=()=>{cancelAnimationFrame(frame);frame=0;last=0;};
      const sync=()=>{stop();if(visible&&!document.hidden&&!motion.matches&&animated)frame=requestAnimationFrame(tick);else {gaze.x=0;gaze.y=0;squish.p=0;blink=-1;wink=-1;paint();}};
      const observer=typeof IntersectionObserver==='function'?new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;sync();}):null;
      observer?.observe(node);
      const move=event=>{if(!interactive||motion.matches)return;const box=node.getBoundingClientRect();pointer=true;target.x=Math.max(-1,Math.min(1,((event.clientX-box.left)/box.width-.5)*2.4));target.y=Math.max(-1,Math.min(1,((event.clientY-box.top)/box.height-.5)*2.4));};
      const leave=()=>{pointer=false;target.x=0;target.y=0;nextLook=time+1.2;};
      const press=()=>{if(!interactive||motion.matches)return;squish.p=.9;squish.v=0;wink=time+.12;};
      const key=event=>{if(event.key===' '||event.key==='Enter'){event.preventDefault();press();}};
      node.addEventListener('pointermove',move);node.addEventListener('pointerleave',leave);node.addEventListener('pointerdown',press);node.addEventListener('keydown',key);
      document.addEventListener('visibilitychange',sync);motion.addEventListener('change',sync);sync();
      return()=>{stop();observer?.disconnect();document.removeEventListener('visibilitychange',sync);motion.removeEventListener('change',sync);node.removeEventListener('pointermove',move);node.removeEventListener('pointerleave',leave);node.removeEventListener('pointerdown',press);node.removeEventListener('keydown',key);};
    },[animated,interactive]);
    const shape=circles.map((circle,index)=><circle key={index} {...circle}/>);
    const stop=(offset,name,opacity)=><stop offset={offset} stopColor={`var(--ui-vf-${name})`} stopOpacity={opacity}/>;
    const eye=(x,ref,name)=><g ref={ref}><rect x={x} y="106" width="18" height="31" rx="9" fill={url('eye')}/><clipPath id={id+'-clip-'+name}><rect x={x} y="106" width="18" height="31" rx="9"/></clipPath><rect x={x} y="108.5" width="18" height="31" rx="9" fill="none" stroke="var(--ui-vf-eye-shade)" strokeWidth="5" filter={url('edge')} clipPath={url('clip-'+name)}/></g>;
    return <div ref={host} className={'ui-vf '+className} data-bg={background||undefined} role={interactive?'button':'img'} tabIndex={interactive?0:undefined} aria-label={interactive?'Make Vellum wink':label} style={validColor(color)?faceColorStyle(color):undefined}>
      <svg viewBox={icon?'25 25 190 190':'0 0 240 240'} aria-hidden="true">
        <defs>
          <filter id={id+'-goo'} x="0" y="0" width="240" height="240" filterUnits="userSpaceOnUse"><feGaussianBlur stdDeviation="3.5"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 28 -12"/></filter>
          {[['soft',7],['halo',9],['edge',1.6],['shade',5]].map(([name,blur])=><filter key={name} id={id+'-'+name} x="0" y="0" width="240" height="240" filterUnits="userSpaceOnUse"><feGaussianBlur stdDeviation={blur}/></filter>)}
          <g id={id+'-shape'} filter={url('goo')}>{shape}<rect x="80" y="100" width="80" height="65"/></g>
          <mask id={id+'-mask'} maskUnits="userSpaceOnUse" x="0" y="0" width="240" height="240"><use href={'#'+id+'-shape'} fill="#fff"/></mask>
          <linearGradient id={id+'-rim'} x1="0" y1="56" x2="0" y2="182" gradientUnits="userSpaceOnUse">{stop(0,'rim')}{stop(1,'white')}</linearGradient>
          <radialGradient id={id+'-body'} cx="120" cy="108" r="78" gradientUnits="userSpaceOnUse">{stop(0,'body-1')}{stop(.6,'body-2')}{stop(1,'body-3')}</radialGradient>
          <linearGradient id={id+'-eye'} x1="0" y1="0" x2="0" y2="1">{stop(0,'white')}{stop(1,'eye')}</linearGradient>
        </defs>
        <ellipse ref={shadow} fill={icon?'none':'var(--ui-vf-shadow)'} cx="120" cy="210" rx="54" ry="7" filter={url('shade')}/>
        <g ref={body}><g ref={head}>
          <use href={'#'+id+'-shape'} fill="var(--ui-vf-halo)" filter={url('halo')}/><use href={'#'+id+'-shape'} fill="var(--ui-vf-edge)" filter={url('edge')}/>
          <g mask={url('mask')}><rect width="240" height="240" fill={url('rim')}/><g filter={url('soft')} fill={url('body')} transform={'translate(0 2) '+around(120,120,'scale(.9 .87)')}>{shape}<rect x="80" y="100" width="80" height="65"/></g><ellipse ref={shine} cx="104" cy="80" rx="30" ry="12" fill="#fff" opacity=".32" filter={url('shade')}/></g>
          <g ref={eyes}>{eye(96.5,left,'l')}{eye(127.5,right,'r')}</g>
        </g></g>
      </svg>
    </div>;
  }
  function FaceSettings({color=DEFAULT_COLOR,onDeviceSettings}) {
    const [draft,setDraft]=useState(color),[hex,setHex]=useState(color),[saving,setSaving]=useState(false),[message,setMessage]=useState('');
    useEffect(()=>{setDraft(color);setHex(color);setMessage('');},[color]);
    const choose=value=>{setHex(value);if(validColor(value))setDraft(value.toLowerCase());setMessage('');};
    const invalid=!validColor(hex),dirty=draft!==color;
    const iconColor=draft===DEFAULT_COLOR?'blue':draft===ORANGE_COLOR?'orange':null;
    const save=async()=>{
      if(invalid||saving||!onDeviceSettings)return;
      setSaving(true);setMessage('');
      try{const receipt=await onDeviceSettings({face_color:draft});setMessage(receipt?.status==='applied'?'Color saved on this device.':receipt?.message||'Color could not be saved. Try again.');}
      catch{setMessage('Color could not be saved. Try again.');}finally{setSaving(false);}
    };
    return <section className="face-settings" aria-labelledby="face-settings-title">
      <h2 id="face-settings-title">Vellum face</h2><p>Choose any color. Preview it here, then apply it to Vellum.</p>
      <div className="face-live-preview" style={faceColorStyle(draft)} aria-label="Live Vellum appearance preview">
        <div className="face-app-preview"><div className="face-preview-header"><VellumFace animated={false} interactive={false}/><span>Vellum</span></div><div className="face-preview-home"><VellumFace/><span>Vellum</span></div><div className="face-preview-composer"><span aria-hidden="true">↑</span></div></div>
        <figure className="face-icon-preview">
          {iconColor ? <img src={`assets/brand/vellum-icon-${iconColor}.png`} alt={`Glow ${iconColor} desktop icon`}/> : <VellumFace background animated={false} interactive={false}/>}
          <figcaption>App icon preview</figcaption>
        </figure>
      </div>
      <div className="face-color-controls">
        <label className="face-color-picker">Face color<input type="color" aria-label="Face color" value={draft} onChange={event=>choose(event.target.value)} disabled={saving}/></label>
        <label className="face-hex-label">Hex color<input aria-label="Face hex color" value={hex} maxLength={7} spellCheck={false} aria-invalid={invalid} aria-describedby={invalid?'face-color-error':undefined} onChange={event=>choose(event.target.value)} disabled={saving}/></label>
        <button type="button" className="btn" onClick={()=>choose(DEFAULT_COLOR)} disabled={saving||draft===DEFAULT_COLOR&&hex===DEFAULT_COLOR}>Reset to blue</button>
        <button type="button" className="btn" aria-pressed={draft===ORANGE_COLOR&&!invalid} onClick={()=>choose(ORANGE_COLOR)} disabled={saving}>Glow Orange</button>
        <button type="button" className="btn" onClick={save} disabled={saving||invalid||!dirty||!onDeviceSettings}>{saving?'Applying…':'Apply color'}</button>
      </div>
      {invalid&&<p id="face-color-error" role="alert">Enter a six-digit hex color, such as #06a3ff.</p>}
      <p className="face-save-status" role="status">{message||'The face updates throughout Vellum after applying. The installed desktop icon stays blue.'}</p>
    </section>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{},{VellumFace,FaceSettings,faceColorStyle});
})();
