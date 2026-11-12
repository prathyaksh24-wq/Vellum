/* Canvas UI Droplets wrapper adapted to Vellum's existing React runtime.
 * Shader and options: canvasui/DropletsVanilla.ts. See canvasui/PROVENANCE.md.
 */
(() => {
  const {useEffect,useRef,useState}=React;
  const options=Object.freeze({intensity:0.5,speed:1,scale:0.4,dropWidth:1,dropLength:1,
    refraction:0.2,blur:0,vignette:0,fallSpeed:1,wiggle:1,staticDrops:0.2,
    interactionRadius:0.3,interactionStrength:0.6,interactionDistortion:3,
    tintStrength:0,tint:[0.5608,0.7059,1]});

  function Droplets({children}) {
    const source=useRef(null),content=useRef(null),output=useRef(null),host=useRef(null);
    const [ready,setReady]=useState(!!window.VellumDroplets);
    const [failed,setFailed]=useState(false);
    const native=ready&&!failed&&window.VellumDroplets.supportsHtmlInCanvas();
    useEffect(()=>{
      const loaded=()=>setReady(true);
      window.addEventListener('vellum:droplets-ready',loaded);
      if(window.VellumDroplets)loaded();
      return()=>window.removeEventListener('vellum:droplets-ready',loaded);
    },[]);
    useEffect(()=>{
      if(!ready)return;
      let instance=null;
      const stop=()=>{instance?.destroy();instance=null;};
      const sync=()=>{
        if(document.hidden){stop();return;}
        if(instance)return;
        try {
          instance=window.VellumDroplets.createDroplets({source:source.current,content:content.current,output:output.current},options);
          if(native&&!instance)setFailed(true);
        }catch {stop();if(native)setFailed(true);}
      };
      // The decorative layer never intercepts clicks. Forward pointer position
      // from the window to the original renderer for its wipe interaction.
      const move=event=>host.current?.dispatchEvent(new PointerEvent('pointermove',{clientX:event.clientX,clientY:event.clientY}));
      const leave=()=>host.current?.dispatchEvent(new PointerEvent('pointerleave'));
      sync();
      document.addEventListener('visibilitychange',sync);
      window.addEventListener('pointermove',move,{passive:true});
      document.documentElement.addEventListener('pointerleave',leave,{passive:true});
      return()=>{
        stop();document.removeEventListener('visibilitychange',sync);
        window.removeEventListener('pointermove',move);
        document.documentElement.removeEventListener('pointerleave',leave);
      };
    },[ready,native]);
    const body=<div ref={content} style={{position:'relative',width:'100%',height:'100%',overflow:'hidden'}}>{children}</div>;
    return <div ref={host} className="droplets-background" style={{position:'absolute',inset:0,pointerEvents:'none'}}>
      <canvas ref={source} layoutsubtree="true" style={native?{position:'absolute',inset:0,width:'100%',height:'100%'}:{display:'none'}}>{native?body:null}</canvas>
      {!native?body:null}
      <canvas ref={output} aria-hidden="true" style={{position:'absolute',inset:0,width:'100%',height:'100%',pointerEvents:'none'}}/>
    </div>;
  }

  function DropletsSetting({enabled,onDeviceSettings}) {
    const [pending,setPending]=useState(false),[error,setError]=useState('');
    const busy=useRef(false);
    async function toggle(){
      if(busy.current||!onDeviceSettings)return;
      busy.current=true;setPending(true);setError('');
      try {
        const receipt=await onDeviceSettings({appearance:{droplets:!enabled}});
        if(receipt?.status!=='applied')setError(receipt?.message||'Droplets could not be saved. Try again.');
      }catch {setError('Droplets could not be saved. Try again.');}
      finally{busy.current=false;setPending(false);}
    }
    return <React.Fragment>
      <div className="set-row"><div>Droplets<span className="sr-sub">Rain on your current background. Keeps the same effect when you change scenes.</span></div>
        <span className="sr-end"><button type="button" className={'sw'+(enabled?' on':'')} style={{border:0,padding:0}} role="switch" aria-label="Droplets" aria-checked={enabled} disabled={pending||!onDeviceSettings} onClick={toggle}/></span>
      </div>
      {error&&<div className="cfg-note" role="alert">{error}</div>}
    </React.Fragment>;
  }
  window.VellumUI.Droplets=Droplets;
  window.VellumUI.DropletsSetting=DropletsSetting;
})();
