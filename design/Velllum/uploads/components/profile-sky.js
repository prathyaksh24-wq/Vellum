/* Canvas engine supplied in vellum-profile-handoff.zip, adapted to Vellum. */
(function(){
const cl=v=>v>0?(v<1?v:1):0,lerp=(a,b,t)=>a+(b-a)*t,eio=x=>{x=cl(x);return x<.5?4*x*x*x:1-Math.pow(-2*x+2,3)/2},eo=x=>1-Math.pow(1-cl(x),3),ss=(a,b,x)=>{const t=cl((x-a)/(b-a));return t*t*(3-2*t)};
const PALS={github:['#0e4429','#006d32','#26a641','#39d353'],ocean:['#0c2d4a','#12508a','#2a88d8','#7cc7ff'],ember:['#4a1a10','#8f2f16','#e0572a','#ffa46b'],grape:['#2d1f4f','#553c9a','#8b5cf6','#c4b5fd'],sunset:['#4a1f3d','#a53f6b','#f2607a','#ffb36b'],mono:['#333333','#5c5c5c','#a3a3a3','#fafafa']};
const EMPTY='#282d34';
const hx=h=>[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)],E0=[40,45,52],rgb=(r,g,b)=>'rgb('+(r+.5|0)+','+(g+.5|0)+','+(b+.5|0)+')';
const cam=(e,dy,de)=>{const yaw=Math.max(0,Math.min(1.431,lerp(0,.7854+dy,e))),el=lerp(1.5708,Math.max(.314,Math.min(1.082,.593+de)),e);return{cs:Math.cos(yaw),sn:Math.sin(yaw),se:Math.sin(el),ce:Math.cos(el)}};
const inQ=(p,o,x,y)=>{let s=0;for(let k=0;k<4;k++){const ax=p[o+k*2],ay=p[o+k*2+1],bx=p[o+(k+1)%4*2],by=p[o+(k+1)%4*2+1],c=(bx-ax)*(y-ay)-(by-ay)*(x-ax);if(Math.abs(c)<1e-9)continue;const g=c>0?1:-1;if(!s)s=g;else if(g!==s)return false}return s!==0};
const qp=(c,p,o,r)=>{if(r<.3){c.moveTo(p[o],p[o+1]);c.lineTo(p[o+2],p[o+3]);c.lineTo(p[o+4],p[o+5]);c.lineTo(p[o+6],p[o+7]);c.closePath();return}c.moveTo((p[o+6]+p[o])/2,(p[o+7]+p[o+1])/2);for(let k=0;k<4;k++){const b=(k+1)%4;c.arcTo(p[o+k*2],p[o+k*2+1],p[o+b*2],p[o+b*2+1],r)}c.closePath()};
/* one scene, two views: a camera swings from straight-down (flat heat map) to the isometric corner (skyline) while bars rise in a wave */
function mountSky(cv,o){
 const ctx=cv.getContext&&cv.getContext('2d'),RM=!!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches);
 let n=0,wks=0,mx=0,months=[],t=0,tg=0,yaw=0,el=0,yG=0,eG=0,W=0,H2=0,H3=0,Hm=0,dpr=1,raf=0,last=0,hov=-1,pin=-1,act=-1,leg=-1,drag=null,ready=false,gut=0,wk,dy,lv,hg,zs,hv,dm,po,fc,od;
 const col=new Float32Array(15),gl=new Float32Array(15);
 const ex=(cm,e,full)=>{const w=lerp(.78,.9,e),of=(1-w)/2;let a=1e9,b=-1e9,c=1e9,d=-1e9;const add=(x,y,z)=>{const px=x*cm.cs-y*cm.sn,py=(x*cm.sn+y*cm.cs)*cm.se-z*cm.ce;if(px<a)a=px;if(px>b)b=px;if(py<c)c=py;if(py>d)d=py};for(let i=0;i<n;i++){const x0=wk[i]+of,y0=dy[i]+of,z=full?hg[i]*e:zs[i];add(x0,y0,z);add(x0+w,y0,z);add(x0,y0+w,z);add(x0+w,y0+w,0);add(x0,y0+w,0);add(x0+w,y0,0)}add(0,7+1.5*e,0);add(wks,7+1.5*e,0);return{a,b,c,d}};
 const layout=()=>{W=Math.round(cv.parentElement.clientWidth);if(!W||!n||!ctx)return;gut=W<520?0:30;dpr=Math.min(2,window.devicePixelRatio||1);const b2=ex(cam(0,0,0),0,true);H2=24+(b2.d-b2.c)/(b2.b-b2.a)*(W-gut-4);const b3=ex(cam(1,0,0),1,true),nat=(b3.d-b3.c)/(b3.b-b3.a)*(W-40)+40;H3=Math.max(Math.min(nat,W*.72,560),Math.min(nat,240));Hm=Math.ceil(Math.max(H2,H3));cv.width=W*dpr;cv.height=Hm*dpr;cv.style.width=W+'px';cv.style.height=Hm+'px';draw()};
 const draw=()=>{if(!W||!n||!ctx)return;const e=eio(t),cm=cam(e,yaw,el),Hc=lerp(H2,H3,e);cv.parentElement.style.height=Hc.toFixed(1)+'px';
  for(let i=0;i<n;i++){const d=(wks>1?wk[i]/(wks-1):0)*.36+dy[i]/6*.06;zs[i]=eo((t-d)/.58)*hg[i]}
  const b=ex(cm,e,false),pad=lerp(2,20,e),left=pad+gut*(1-e),top=pad+20*(1-e),aw=W-left-pad,ah=Hc-top-pad,bw=Math.max(1e-6,b.b-b.a),bh=Math.max(1e-6,b.d-b.c),s=Math.min(aw/bw,ah/bh),ox=left+(aw-bw*s)/2-b.a*s,oy=top+(ah-bh*s)/2-b.c*s,{cs,sn,se,ce}=cm;
  const PX=(x,y)=>ox+(x*cs-y*sn)*s,PY=(x,y,z)=>oy+((x*sn+y*cs)*se-z*ce)*s;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,Hm);
  od.sort((a,c)=>(wk[a]+.5)*sn+(dy[a]+.5)*cs-((wk[c]+.5)*sn+(dy[c]+.5)*cs));
  const w=lerp(.78,.9,e),of=(1-w)/2,rad=lerp(.17,.03,e)*s,lift=.7*e,ex0=col[0],ey0=col[1],ez0=col[2];
  for(let k=0;k<n;k++){const i=od[k],x0=wk[i]+of,y0=dy[i]+of,x1=x0+w,y1=y0+w,z=zs[i]+hv[i]*lift,q=i*24;
   po[q]=PX(x0,y0);po[q+1]=PY(x0,y0,z);po[q+2]=PX(x1,y0);po[q+3]=PY(x1,y0,z);po[q+4]=PX(x1,y1);po[q+5]=PY(x1,y1,z);po[q+6]=PX(x0,y1);po[q+7]=PY(x0,y1,z);
   po[q+8]=PX(x0,y1);po[q+9]=PY(x0,y1,0);po[q+10]=PX(x1,y1);po[q+11]=PY(x1,y1,0);po[q+12]=po[q+4];po[q+13]=po[q+5];po[q+14]=po[q+6];po[q+15]=po[q+7];
   po[q+16]=PX(x1,y0);po[q+17]=PY(x1,y0,0);po[q+18]=po[q+10];po[q+19]=po[q+11];po[q+20]=po[q+4];po[q+21]=po[q+5];po[q+22]=po[q+2];po[q+23]=po[q+3];
   const tall=z*ce*s;let f=0;if(tall>.35&&w*cs*s>.35)f|=1;if(tall>.35&&w*sn*s>.35)f|=2;fc[i]=f;
   const L=lv[i]*3;let r=col[L],g=col[L+1],bl=col[L+2];const d=dm[i];if(d>.002){r+=(ex0-r)*.72*d;g+=(ey0-g)*.72*d;bl+=(ez0-bl)*.72*d}const h=hv[i];if(h>.002){const m=.2*h;r+=(255-r)*m;g+=(255-g)*m;bl+=(255-bl)*m}
   if(f&1){ctx.beginPath();qp(ctx,po,q+8,0);ctx.fillStyle=rgb(r*.84,g*.84,bl*.84);ctx.fill()}if(f&2){ctx.beginPath();qp(ctx,po,q+16,0);ctx.fillStyle=rgb(r*.68,g*.68,bl*.68);ctx.fill()}
   ctx.beginPath();qp(ctx,po,q,rad);ctx.fillStyle=rgb(r,g,bl);ctx.fill();if(h>.02){ctx.strokeStyle='rgba(255,255,255,'+(.85*h).toFixed(3)+')';ctx.lineWidth=1.5;ctx.stroke()}}
  ctx.font='400 10px '+getComputedStyle(cv).fontFamily;const a2=1-ss(0,.4,e),a3=ss(.62,1,e);
  const lab=(a,fr)=>{if(a<.004)return;ctx.fillStyle='rgba(165,165,165,'+a.toFixed(3)+')';ctx.textAlign='left';ctx.textBaseline=fr?'top':'bottom';let ed=-1e9;for(const m of months){const x=fr?PX(m[0]+.5,7.3):PX(m[0]+of,-.3),tw=ctx.measureText(m[1]).width;if(x<ed||x+tw>W)continue;ctx.fillText(m[1],x,fr?PY(m[0]+.5,7.3,0)+2:PY(m[0]+of,-.3,0)-3);ed=x+tw+8}};lab(a2,0);lab(a3,1);
  if(a2>.004&&gut>0){ctx.fillStyle='rgba(165,165,165,'+a2.toFixed(3)+')';ctx.textAlign='right';ctx.textBaseline='middle';[[1,'Mon'],[3,'Wed'],[5,'Fri']].forEach(([dd,l])=>ctx.fillText(l,PX(0,dd+.5)-6,PY(0,dd+.5,0)))}
  if(act>=0&&act<n){const i=act,z=zs[i]+hv[i]*lift;o.tip(i,PX(wk[i]+.5,dy[i]+.5),Math.min(PY(wk[i]+of,dy[i]+of,z),PY(wk[i]+of+w,dy[i]+of,z),PY(wk[i]+of,dy[i]+of+w,z)))}else o.tip(-1)};
 const tick=now=>{raf=0;const dt=Math.min(.05,Math.max(0,(now-last)/1000));last=now;let mv=0;
  if(t!==tg){const st=RM?1:dt*1000/1300;t=tg>t?Math.min(tg,t+st):Math.max(tg,t-st);mv=1}
  const ko=RM?1:1-Math.exp(-dt*12);yaw+=(yG-yaw)*ko;el+=(eG-el)*ko;if(Math.abs(yG-yaw)>1e-4||Math.abs(eG-el)>1e-4)mv=1;else{yaw=yG;el=eG}
  const kc=RM?1:1-Math.exp(-dt*7);for(let k=0;k<15;k++){const d=gl[k]-col[k];if(Math.abs(d)>.4){col[k]+=d*kc;mv=1}else col[k]=gl[k]}
  const kh=RM?1:1-Math.exp(-dt*16),kd=RM?1:1-Math.exp(-dt*10);for(let i=0;i<n;i++){const h=i===act?1:0,d=leg>=0&&lv[i]!==leg?1:0;if(hv[i]!==h){hv[i]=Math.abs(h-hv[i])<.003?h:hv[i]+(h-hv[i])*kh;mv=1}if(dm[i]!==d){dm[i]=Math.abs(d-dm[i])<.003?d:dm[i]+(d-dm[i])*kd;mv=1}}
  draw();if(mv)raf=requestAnimationFrame(tick)};
 const kick=()=>{if(raf||!ctx)return;last=performance.now();raf=requestAnimationFrame(tick)};
 const setAct=()=>{const nx=hov>=0?hov:pin;if(nx===act)return;act=nx;o.onActive(nx);kick()};
 const loc=e=>{const r=cv.getBoundingClientRect();return[e.clientX-r.left,e.clientY-r.top]};
 const hit=(x,y)=>{for(let k=n-1;k>=0;k--){const i=od[k],q=i*24;if(inQ(po,q,x,y)||(fc[i]&1&&inQ(po,q+8,x,y))||(fc[i]&2&&inQ(po,q+16,x,y)))return i}return -1};
 cv.onpointerdown=e=>{if(e.button!==0)return;const can=tg===1;drag={id:e.pointerId,x:e.clientX,y:e.clientY,yaw:yG,el:eG,m:0,can,mouse:e.pointerType==='mouse'};if(can)try{cv.setPointerCapture(e.pointerId)}catch(_){}};
 cv.onpointermove=e=>{if(drag&&drag.can&&e.pointerId===drag.id){const dx=e.clientX-drag.x,dyy=e.clientY-drag.y;if(drag.m||Math.hypot(dx,dyy)>4){drag.m=1;yG=Math.max(-.646,Math.min(.646,drag.yaw+dx*.006));if(drag.mouse)eG=Math.max(-.279,Math.min(.489,drag.el+dyy*.004));cv.style.cursor='grabbing';hov=-1;setAct();kick();return}}if(e.pointerType!=='mouse')return;const[x,y]=loc(e),i=hit(x,y);if(i!==hov){hov=i;setAct()}cv.style.cursor=tg===1?'grab':i>=0?'pointer':'default'};
 cv.onpointerup=e=>{if(!drag||e.pointerId!==drag.id)return;const mv=drag.m;drag=null;try{cv.releasePointerCapture(e.pointerId)}catch(_){}cv.style.cursor=tg===1?'grab':'default';if(mv)return;const[x,y]=loc(e),i=hit(x,y);pin=i===pin?-1:i;if(e.pointerType!=='mouse')hov=-1;setAct();o.onPick(pin)};
 cv.onpointercancel=()=>{drag=null;hov=-1;cv.style.cursor=tg===1?'grab':'default';setAct()};cv.onpointerleave=()=>{if(drag)return;hov=-1;setAct()};cv.ondblclick=()=>{yG=0;eG=0;kick()};
 cv.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','Escape'].includes(e.key)||!n)return;e.preventDefault();if(e.key==='Escape'){pin=-1;hov=-1;setAct();o.onPick(-1);return}let i=pin>=0?pin:n-1;if(e.key==='Home')i=0;if(e.key==='End')i=n-1;if(pin>=0){if(e.key==='ArrowLeft')i-=7;if(e.key==='ArrowRight')i+=7;if(e.key==='ArrowUp')i-=1;if(e.key==='ArrowDown')i+=1;if(e.key==='Home')i=0;if(e.key==='End')i=n-1}i=Math.max(0,Math.min(n-1,i));pin=i;hov=-1;setAct();o.onPick(i)};
 return{
  setData(cs,w,ms){n=cs.length;wks=w;months=ms;wk=Float32Array.from(cs,c=>c.w);dy=Float32Array.from(cs,c=>c.d);const nz=cs.map(c=>c.c).filter(c=>c>0).sort((a,b)=>a-b),busy=nz.length?nz[Math.floor(.95*(nz.length-1))]:0;mx=nz.length?nz[nz.length-1]:0;
   lv=Uint8Array.from(cs,c=>c.c<=0?0:busy<=0?4:1+Math.min(3,Math.floor(c.c/busy*4)));hg=Float32Array.from(cs,c=>c.c>0&&mx>0?.4+Math.pow(c.c/mx,.85)*7.2:.2);zs=new Float32Array(n);hv=new Float32Array(n);dm=new Float32Array(n);po=new Float32Array(n*24);fc=new Uint8Array(n);od=Array.from({length:n},(_,i)=>i);if(RM)t=tg;layout();kick()},
  setPal(name){const p=[E0,...PALS[name].map(hx)];p.forEach((c,k)=>c.forEach((v,j)=>gl[k*3+j]=v));if(!ready||RM){col.set(gl);ready=true}kick()},
  setView(v){tg=v==='3d'?1:0;if(!tg){yG=0;eG=0}cv.style.cursor=tg?'grab':'default';kick()},
  setLegend(l){leg=l;kick()},setPin(i){pin=i;setAct()},resize(){layout();kick()},
  destroy(){cancelAnimationFrame(raf);cv.onpointerdown=cv.onpointermove=cv.onpointerup=cv.onpointercancel=cv.onpointerleave=cv.ondblclick=cv.onkeydown=null}}}

window.VellumUI=Object.assign(window.VellumUI||{},{ProfileSky:{mountSky,PALS,EMPTY}});
})();
