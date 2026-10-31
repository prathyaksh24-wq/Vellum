/* Presentation over actual received text; never generates answer or reasoning content. */
(function(){
  const DEFAULT={style:'ink',loading:'cascade',speed:12,pencil:true,thinking:true,citations:'auto'};
  let context;
  const h=(...args)=>window.React.createElement(...args);
  const getContext=()=>context || (context=window.React.createContext(DEFAULT));
  function ResponsePreferencesProvider({value,children}){return h(getContext().Provider,{value:{...DEFAULT,...value}},children);}
  function useResponsePreferences(){return window.React.useContext(getContext());}
  function useReducedMotion(){
    const [reduce,setReduce]=window.React.useState(()=>!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    window.React.useEffect(()=>{const media=window.matchMedia?.('(prefers-reduced-motion: reduce)');if(!media)return;const change=()=>setReduce(media.matches);media.addEventListener?.('change',change);return()=>media.removeEventListener?.('change',change);},[]);
    return reduce;
  }
  function useStreamingText(text,streaming,speed=12){
    const reduced=useReducedMotion(), everLive=window.React.useRef(!!streaming);
    if(streaming)everLive.current=true;
    const [visible,setVisible]=window.React.useState(()=>streaming && !reduced?'':text);
    const shown=window.React.useRef(visible), target=window.React.useRef(text), timer=window.React.useRef(null), rate=window.React.useRef(speed);
    target.current=text;
    rate.current=speed;
    const finish=()=>{clearTimeout(timer.current);timer.current=null;shown.current=target.current;setVisible(target.current);};
    window.React.useEffect(()=>()=>clearTimeout(timer.current),[]);
    window.React.useEffect(()=>{
      if(reduced || !everLive.current || !streaming){finish();return;}
      if(!text.startsWith(shown.current)){
        let same=0;while(same<Math.min(text.length,shown.current.length) && text[same]===shown.current[same])same++;
        shown.current=text.slice(0,same);setVisible(shown.current);
      }
      if(shown.current.length>=text.length)return;
      if(timer.current!==null)return;
      const step=()=>{
        timer.current=null;
        const current=shown.current.length, tail=target.current.slice(current);
        if(!tail)return;
        const words=tail.match(/\s*\S+\s*/gu) || [tail];
        const take=Math.min(8,Math.max(1,Math.ceil(words.length/12)));
        const end=current+words.slice(0,take).join('').length;
        shown.current=target.current.slice(0,end);setVisible(shown.current);
        if(end<target.current.length)timer.current=setTimeout(step,1000/Math.max(2,Math.min(24,rate.current)));
      };
      timer.current=setTimeout(step,shown.current?1000/Math.max(2,Math.min(24,speed)):0);
    },[text,speed,reduced,streaming]);
    return {text:reduced?text:visible,pending:!reduced && visible!==text,animated:everLive.current && !reduced,finish};
  }
  function AnimatedStatus({text,variant='cascade'}){
    const reduced=useReducedMotion(),[scrambled,setScrambled]=window.React.useState(text);
    window.React.useEffect(()=>{
      if(reduced || variant!=='scramble'){setScrambled(text);return;}
      let start=performance.now();const chars='#%&@$?/ABCDEFG';
      const timer=setInterval(()=>{const progress=Math.min(1,(performance.now()-start)/450),count=Math.ceil(text.length*progress);
        setScrambled([...text].map((c,i)=>i<count || /\s/.test(c)?c:chars[(i+count)%chars.length]).join(''));
        if(progress===1)clearInterval(timer);
      },30);
      return()=>clearInterval(timer);
    },[text,variant,reduced]);
    return h('span',{className:'agent-loading-text agent-loading-'+variant,'aria-label':text},
      h('span',{'aria-hidden':true,key:text},variant==='cascade' && !reduced
        ? [...text].map((char,index)=>h('span',{key:index,className:'agent-loading-character',style:{animationDelay:Math.min(index*18,250)+'ms'}},char))
        : variant==='scramble'?scrambled:text));
  }
  function StreamingSettings({preferences,onDeviceSettings}){
    const prefs={...DEFAULT,...preferences},[busy,setBusy]=window.React.useState(false),[error,setError]=window.React.useState('');
    const [draftSpeed,setDraftSpeed]=window.React.useState(prefs.speed),[preview,setPreview]=window.React.useState(null);
    window.React.useEffect(()=>setDraftSpeed(prefs.speed),[prefs.speed]);
    const save=async patch=>{setBusy(true);setError('');try{const receipt=await onDeviceSettings({streaming:patch});if(receipt?.status!=='applied')throw new Error(receipt?.message || 'Streaming preference was not saved.');}catch(err){setError(err.message);}finally{setBusy(false);}};
    const row=(title,description,control)=>h('div',{className:'set-row'},h('div',null,title,h('p',{className:'cfg-note'},description)),h('span',{className:'sr-end'},control));
    const select=(name,options,value,onChange)=>h(window.VellumUI.VSelect,{ariaLabel:name,value,disabled:busy,onValueChange:onChange,className:'pdrop-select',menuWidth:214,options:options.map(([value,label])=>({value,label}))});
    return h('section',{className:'streaming-settings'},h('div',{className:'set-h'},'Responses'),
      h('p',{className:'cfg-note'},'Choose how Vellum’s actual responses arrive. These settings change presentation; the model and tools still determine the content.'),
      row('Streaming style','Classic fades in new words. Provenance ink lets fresh text settle into the page.',select('Streaming style',[['classic','Classic'],['ink','Provenance ink']],prefs.style,value=>save({style:value}))),
      row('Loading indicator','Activity orbs follow the model’s real work, thinking, and search events.',h('span',{className:'streaming-orb-preview'},h(window.VellumUI.ThinkingOrb,{state:'working',size:22}),'Activity orbs')),
      row('Streaming speed','Approximate words per second. Does not delay requests to the model.',h('label',{className:'streaming-speed'},h('input',{type:'range',min:2,max:24,step:1,value:draftSpeed,disabled:busy,'aria-label':'Streaming speed',
        onChange:event=>setDraftSpeed(Number(event.target.value)),onPointerUp:()=>save({speed:draftSpeed}),onKeyUp:event=>{if(['ArrowLeft','ArrowRight','Home','End','PageUp','PageDown'].includes(event.key))save({speed:Number(event.currentTarget.value)});}}),h('output',null,draftSpeed+' words/s'))),
      row('Show inferred text in pencil','Marks interpretations explicitly identified in book responses.',h('input',{type:'checkbox',checked:prefs.pencil,disabled:busy,'aria-label':'Show inferred text in pencil',onChange:event=>save({pencil:event.target.checked})})),
      row('Show thought process','Show the thinking text or reasoning summary supplied by the model.',h('input',{type:'checkbox',checked:prefs.thinking,disabled:busy,'aria-label':'Show thought process',onChange:event=>save({thinking:event.target.checked})})),
      row('Citations','Automatic shows evidence linked to the answer. Ordinary replies and calculations stay clear.',select('Citations',[['auto','When relevant'],['always','All available sources'],['hidden','Hide source list']],prefs.citations,value=>save({citations:value}))),
      h('div',{className:'streaming-preview'},h('div',{className:'agent-detail-label'},'Presentation preview'),h('span',{className:'streaming-orb-preview'},h(window.VellumUI.ThinkingOrb,{state:'working',size:22}),'Preparing a response'),
        h('button',{type:'button',className:'btn',onClick:()=>setPreview({id:Date.now(),text:'Words arrive steadily, then settle into the page. Your real response uses the same presentation.',streaming:true,suppressActivity:true})},'Replay text preview'),
        preview && h(ResponsePreferencesProvider,{value:prefs},h(PreviewText,{key:preview.id,msg:preview}))),
      error && h('p',{role:'alert'},error),h('p',{className:'cfg-note'},'Reduced motion uses immediate text with no animation. Thinking details use the model’s available thinking output or reasoning summary.'));
  }
  function PreviewText({msg}){
    const prefs=useResponsePreferences(),reveal=useStreamingText(msg.text,true,prefs.speed);
    return h('div',{className:'agent-response-content agent-text-'+prefs.style},h(window.VellumUI.AnswerMarkdown,{text:reveal.text,animate:reveal.animated}));
  }
  window.VellumUI={...window.VellumUI,ResponsePreferencesProvider,useResponsePreferences,useStreamingText,AnimatedStatus,StreamingSettings};
})();
