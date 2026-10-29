/* Original DVK Lab visual shaders, unchanged. Source URLs and hashes:
 * assets/backgrounds/dvk/provenance.json. Lifecycle adapter: DvkMotionBackground.jsx.
 */
window.VellumUI = window.VellumUI || {};
window.VellumUI.DvkMotionShaders = {
  'nimbus': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
// Flow-map advection: the texture streams along \`dir\` forever without sliding off the image.
// Two copies offset half a cycle apart crossfade, so the reset of each is never visible.
// iu: image uv, dir: flow direction (image uv units / cycle), period: seconds per cycle, lod: blur
vec3 flowSample(vec2 iu,vec2 dir,float period,float lod){
  float ph=fract(t/period);
  float ph2=fract(t/period+.5);
  float w=abs(ph-.5)*2.;                                 // weight of copy 2 (0 when copy 1 is mid-cycle)
  vec3 a=textureLod(img,iu-dir*(ph-.5),lod*.4).rgb;
  vec3 b=textureLod(img,iu-dir*(ph2-.5),lod*.4).rgb;
  return mix(a,b,w);
}
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.08);
  iu+=(m-.5)*vec2(.012,.008);                          // slight pointer parallax
  // wind: mostly down-right along the wisps, bent by a slow noise field so areas move differently
  float n=dn(iu*3.+t*.02);
  vec2 wind=vec2(.9,-.45)+vec2(n-.5,dn(iu*3.+7.-t*.02)-.5)*.6;
  // fine turbulence on top so the wisps curl
  iu+=(vec2(dn(iu*9.+t*.08),dn(iu*9.+3.-t*.08))-.5)*.006;
  vec3 c=flowSample(iu,wind*.035,9.,.6);
  fragColor=vec4(grain(c,.025),1.);
}
`,
    maps:null, sky:null
  },
  'daybreak': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.1);
  iu.y+=.025*sin(t*.09);                                // the glow slowly rises and settles
  iu=drift(iu,.05,.04);
  float hot=smoothstep(.15,.6,dot(textureLod(img,iu,4.).rgb,vec3(.5,.4,.1)));
  iu.x+=.0018*sin(iu.y*90.-t*2.4)*hot;                  // faint heat shimmer where it's brightest
  vec3 c=soft(iu,1.);
  c*=1.+.08*sin(t*.35)*hot;                             // breathing intensity
  fragColor=vec4(grain(c,.03),1.);
}
`,
    maps:null, sky:null
  },
  'eclipse': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.06);
  iu=drift(iu,.035,.05);                               // gentle, so the disc edge stays put for the orbit rings
  vec3 c=soft(iu,2.5);
  vec2 g=gl_FragCoord.xy+fract(t*9.)*100.;              // chunky film grain, slightly different per channel
  c+=(vec3(hash(g),hash(g+17.),hash(g+31.))-.5)*.07;
  fragColor=vec4(c,1.);
}
`,
    maps:null, sky:null
  },
  'dusk': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.1+.02*sin(t*.05));
  iu=drift(iu,.06,.04);
  vec3 c=soft(iu,1.5);
  fragColor=vec4(grain(c,.025),1.);
}
`,
    maps:null, sky:null
  },
  'meadow': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
// Depth parallax from maps.r (white = near). The screen point s shows image point i where
// s = i + cam*(depth(i) - focal). Solve for i with a few fixed-point steps: near layers slide
// over far ones with no tearing, the way a real camera move would.
float depthAt(vec2 iu){return textureLod(maps,iu,1.).r;}
vec2 parallax(vec2 iu,vec2 cam,float focal){
  vec2 i=iu;
  for(int k=0;k<5;k++){ i=iu-cam*(depthAt(i)-focal); }
  return i;
}
// a slow, looping camera drift plus the pointer
vec2 camMove(float amp,float speed){
  vec2 auto_=vec2(sin(t*speed),sin(t*speed*.71+1.3)*.6)*amp;
  return auto_+(m-.5)*vec2(2.,1.4)*amp;
}
// mist: soft drifting banks. dir = drift direction, scale = bank size
float mist(vec2 p,vec2 dir,float scale){
  vec2 q=p*scale+dir*t;
  float n=dn(q)*.55+dn(q*2.1+vec2(3.1,1.7)-dir*t*.6)*.3+dn(q*4.3-dir*t*.3)*.15;
  return smoothstep(.35,.85,n);
}
// light shafts: soft streaks along \`dir\` (unit, image space), shimmering slowly
float shafts(vec2 p,vec2 dir,float freq){
  vec2 nrm=vec2(-dir.y,dir.x);
  float x=dot(p,nrm)*freq;
  float a=dn(vec2(x,t*.08))*.6+dn(vec2(x*2.3+5.,t*.11))*.4;
  return smoothstep(.45,.9,a);
}
// console screen box, measured on the photo (uv, y up)
const vec4 SCREEN=vec4(.42,.456,.54,.566);
float box(vec2 p,vec4 b,float s){return smoothstep(b.x-s,b.x+s,p.x)*smoothstep(b.z+s,b.z-s,p.x)*smoothstep(b.y-s,b.y+s,p.y)*smoothstep(b.w+s,b.w-s,p.y);}
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.08);
  iu=parallax(iu,camMove(.012,.11),.25);
  float d=depthAt(iu);
  // wind: gusts roll across the meadow left→right; near flowers sway most, the console stays put
  float gust=.5+.5*sin(t*.5-iu.x*3.)*dn(vec2(t*.3,iu.x*2.));
  float steady=1.-box(iu,vec4(.38,.36,.6,.6),.03);
  float sway=smoothstep(.15,.6,d)*steady;
  iu.x+=(sin(t*1.7+iu.x*14.+iu.y*6.)*.6+sin(t*2.9-iu.x*23.)*.4)*.0045*sway*(.4+gust);
  iu.y+=sin(t*1.3+iu.x*11.)*.0015*sway;
  vec3 c=textureLod(img,iu,0.).rgb;
  // console screen: soft flicker, rolling scanline, glow that breathes into the grass
  float sc=box(iu,SCREEN,.006);
  float scan=.5+.5*sin((iu.y-t*.06)*900.);
  float roll=smoothstep(.0,.03,abs(fract(iu.y*8.-t*.4)-.5));
  float flick=.94+.06*dn(vec2(t*14.,0.));
  c=mix(c,c*flick*(.96+.04*scan)*(.94+.06*roll),sc);
  vec2 gp=(iu-vec2(.48,.5))*vec2(ia,1.);
  c+=vec3(.55,1.,.8)*exp(-dot(gp,gp)*55.)*(.05+.04*sin(t*1.1))*(1.-sc);
  // petals tumbling through the sky
  float skyM=1.-smoothstep(.08,.2,d);
  for(int i=0;i<7;i++){
    float fi=float(i);
    float sp=.025+.02*hash(vec2(fi,3.));
    vec2 p=vec2(fract(hash(vec2(fi,1.))+t*sp),.62+.33*hash(vec2(fi,2.))+.03*sin(t*.7+fi*2.));
    vec2 q=(iu-p)*vec2(ia,1.);
    float a=t*(1.+fi*.3)+fi; q=mat2(cos(a),-sin(a),sin(a),cos(a))*q;
    float pet=smoothstep(1.,.6,length(q*vec2(260.,520.)));
    vec3 pc=mix(vec3(1.,.55,.4),vec3(1.,.7,.85),hash(vec2(fi,7.)));
    c=mix(c,pc,pet*.85*skyM);
  }
  fragColor=vec4(grain(c,.018),1.);
}
`,
    maps:"maps.png", sky:null
  },
  'stratosphere': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.04);
  iu.y+=.012*sin(t*.07);                                // the horizon slowly rises and settles
  iu=drift(iu,.02,.04);
  vec3 c=soft(iu,1.5);
  // dawn breathes along the horizon, with a faint heat shimmer right on the line
  float hz=smoothstep(.35,.0,iu.y);
  c*=1.+hz*(.06*sin(t*.3)+.03*sin(t*.83));
  // sparse stars, only in the darkest part of the sky; each twinkles on its own clock
  float dark=smoothstep(.2,.05,dot(c,vec3(.33)));
  vec2 g=gl_FragCoord.xy/r.y*vec2(180.);
  vec2 id=floor(g),f=fract(g)-.5;
  float rnd=hash(id);
  vec2 off=(vec2(hash(id+1.7),hash(id+9.1))-.5)*.6;
  float star=smoothstep(.07,.0,length(f-off))*step(.965,rnd);
  float tw=.55+.45*sin(t*(1.+rnd*3.)+rnd*40.);
  c+=vec3(.85,.9,1.)*star*tw*dark*(.5+.7*hash(id+3.3));
  fragColor=vec4(grain(c,.02),1.);
}
`,
    maps:null, sky:null
  },
  'cloudline': {
    vert:`attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`,
    frag:`
precision highp float;
uniform vec2 r; uniform float t; uniform vec2 m;
// Volumetric cloud sea at dawn: density from 3D fbm shaped into a layer, light marched toward the sun
// (Beer-Lambert + powder), Henyey-Greenstein phase for the silver lining, distance fog into the sky.
float h31(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float n3(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
  return mix(mix(mix(h31(i),h31(i+vec3(1,0,0)),f.x),mix(h31(i+vec3(0,1,0)),h31(i+vec3(1,1,0)),f.x),f.y),
             mix(mix(h31(i+vec3(0,0,1)),h31(i+vec3(1,0,1)),f.x),mix(h31(i+vec3(0,1,1)),h31(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p,int o){float v=0.,a=.5;for(int i=0;i<5;i++){if(i>=o)break;v+=a*n3(p);p=p*2.03+vec3(.31,.71,.13);a*=.5;}return v;}
vec3 SUN;
float dens(vec3 p,int o){
  vec3 q=p*vec3(.55,.9,.55)+vec3(t*.04,0.,t*.03);
  float cover=n3(vec3(p.xz*.09,t*.01))*.7+n3(vec3(p.xz*.21,3.))*.3;   // cloud banks vs open gaps
  float n=fbm(q,o);
  float top=.6+1.2*cover;                                              // taller cumulus where cover is high
  float prof=smoothstep(0.,.3,p.y)*smoothstep(top,top-.55,p.y);
  return clamp((n*prof+cover*.35-.52)*5.,0.,1.);
}
vec3 sky(vec3 d){
  float y=max(d.y,0.);
  vec3 c=mix(vec3(1.,.74,.62),vec3(.55,.62,.86),pow(y,.5));
  c=mix(c,vec3(.24,.32,.6),smoothstep(.35,1.,y));
  float s=max(dot(d,SUN),0.);
  c+=vec3(1.,.72,.48)*pow(s,8.)*.5+vec3(1.,.9,.75)*smoothstep(.9993,.9996,s)*3.;
  return c;
}
float hg(float c,float g){float g2=g*g;return (1.-g2)/(4.*3.14159*pow(1.+g2-2.*g*c,1.5));}
void main(){
  vec2 uv=(gl_FragCoord.xy-.5*r)/r.y;
  SUN=normalize(vec3(.55,.16,-1.));
  float yaw=(m.x-.5)*.35+.08*sin(t*.05);
  vec3 ro=vec3(0.,2.3+.06*sin(t*.3),-t*1.1);
  vec3 rd=normalize(vec3(uv.x,uv.y-.16+(m.y-.5)*.1,-1.35));
  rd=vec3(rd.x*cos(yaw)+rd.z*sin(yaw),rd.y,-rd.x*sin(yaw)+rd.z*cos(yaw));
  vec3 bg=sky(rd);
  // intersect the cloud slab y in [0,1.9]
  float t0=0., t1=0.;
  if(rd.y<-.001){ t0=max((2.-ro.y)/rd.y,0.); t1=min((0.-ro.y)/rd.y,40.); }
  vec3 col=vec3(0.); float T=1.;
  if(t1>t0){
    const int N=56;
    float dt=(t1-t0)/float(N);
    float tt=t0+dt*h31(vec3(gl_FragCoord.xy,fract(t)*7.));
    float cosA=dot(rd,SUN);
    float ph=mix(hg(cosA,.55),hg(cosA,-.2),.35)*6.;
    for(int i=0;i<N;i++){
      vec3 p=ro+rd*tt;
      float dist=tt;
      int oct=dist<14.?5:3;
      float d=dens(p,oct);
      if(d>.01){
        float ld=0.;
        for(int j=1;j<=4;j++)ld+=dens(p+SUN*float(j)*.24,3);
        float light=exp(-ld*1.5)*(1.-exp(-d*4.));          // Beer + powder
        vec3 amb=mix(vec3(.36,.38,.55),vec3(.95,.86,.86),smoothstep(0.,1.6,p.y));
        vec3 sc=amb*.5+vec3(1.,.8,.6)*light*ph*1.5;
        float a=1.-exp(-d*dt*4.);
        // aerial perspective: distant clouds melt into the horizon colour
        float fog=1.-exp(-dist*.035);
        sc=mix(sc,sky(vec3(rd.x,.02,rd.z)),fog);
        col+=T*a*sc; T*=1.-a;
        if(T<.02)break;
      }
      tt+=dt;
    }
  }
  col+=T*bg;
  // sun bloom through everything
  col+=vec3(1.,.8,.6)*pow(max(dot(rd,SUN),0.),40.)*.25;
  col=col/(1.+col*.32)*1.22;              // soft shoulder: keep the sunlit tops from clipping
  col=pow(col,vec3(.95));
  vec2 q=gl_FragCoord.xy/r;
  col*=1.-.22*dot(q-.5,q-.5)*2.;
  col+=(h31(vec3(gl_FragCoord.xy,fract(t)))-.5)*.012;
  gl_FragColor=vec4(col,1.);
}
`,
    kind:"procedural",
    context:"webgl",
    renderScale:0.5,
    previewScale:0.5,
    stillTime:20,
    smoothing:0.04,
    fallback:"linear-gradient(180deg,#5d6fae,#c9b7cf 40%,#ffd2bb 55%,#fff1ea 62%,#d4c4d6)"
  },
  'grotto': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
// Flow-map advection: the texture streams along \`dir\` forever without sliding off the image.
// Two copies offset half a cycle apart crossfade, so the reset of each is never visible.
// iu: image uv, dir: flow direction (image uv units / cycle), period: seconds per cycle, lod: blur
vec3 flowSample(vec2 iu,vec2 dir,float period,float lod){
  float ph=fract(t/period);
  float ph2=fract(t/period+.5);
  float w=abs(ph-.5)*2.;                                 // weight of copy 2 (0 when copy 1 is mid-cycle)
  vec3 a=textureLod(img,iu-dir*(ph-.5),lod*.4).rgb;
  vec3 b=textureLod(img,iu-dir*(ph2-.5),lod*.4).rgb;
  return mix(a,b,w);
}
// Depth parallax from maps.r (white = near). The screen point s shows image point i where
// s = i + cam*(depth(i) - focal). Solve for i with a few fixed-point steps: near layers slide
// over far ones with no tearing, the way a real camera move would.
float depthAt(vec2 iu){return textureLod(maps,iu,1.).r;}
vec2 parallax(vec2 iu,vec2 cam,float focal){
  vec2 i=iu;
  for(int k=0;k<5;k++){ i=iu-cam*(depthAt(i)-focal); }
  return i;
}
// a slow, looping camera drift plus the pointer
vec2 camMove(float amp,float speed){
  vec2 auto_=vec2(sin(t*speed),sin(t*speed*.71+1.3)*.6)*amp;
  return auto_+(m-.5)*vec2(2.,1.4)*amp;
}
// mist: soft drifting banks. dir = drift direction, scale = bank size
float mist(vec2 p,vec2 dir,float scale){
  vec2 q=p*scale+dir*t;
  float n=dn(q)*.55+dn(q*2.1+vec2(3.1,1.7)-dir*t*.6)*.3+dn(q*4.3-dir*t*.3)*.15;
  return smoothstep(.35,.85,n);
}
// light shafts: soft streaks along \`dir\` (unit, image space), shimmering slowly
float shafts(vec2 p,vec2 dir,float freq){
  vec2 nrm=vec2(-dir.y,dir.x);
  float x=dot(p,nrm)*freq;
  float a=dn(vec2(x,t*.08))*.6+dn(vec2(x*2.3+5.,t*.11))*.4;
  return smoothstep(.45,.9,a);
}
// measured on the photo (uv, y up)
const vec2 FALL_X=vec2(.455,.605);
const float POOL=.30, FALL_TOP=.80;
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  // slow breathing push-in toward the falls + gentle drift
  float push=1.06+.035*(.5-.5*cos(t*.08));
  vec2 iu=cover(uv,push);
  iu=parallax(iu,camMove(.01,.09),.15);
  float d=depthAt(iu);

  vec3 c=textureLod(img,iu,0.).rgb;
  // waterfall: stream the bright strands downward
  float fx=smoothstep(FALL_X.x,FALL_X.x+.015,iu.x)*smoothstep(FALL_X.y,FALL_X.y-.015,iu.x);
  float fy=smoothstep(POOL-.01,POOL+.03,iu.y)*smoothstep(FALL_TOP,FALL_TOP-.05,iu.y);
  float bright=smoothstep(.35,.6,dot(c,vec3(.33)));
  float fall=fx*fy;
  if(fall>0.){
    vec2 wob=vec2((dn(vec2(iu.x*90.,t*.6))-.5)*.002,0.);
    vec3 f=flowSample(iu+wob,vec2(0.,-.06),1.6,.15);
    c=mix(c,f,fall*(.35+.65*bright));
  }
  // pool: ripples ring out from the base of the falls + specular shimmer
  if(iu.y<POOL){
    float k=(POOL-iu.y)/POOL;
    vec2 q=(iu-vec2(.53,POOL))*vec2(ia,3.);
    float ring=sin(length(q)*60.-t*2.2);
    vec2 w=vec2(sin(iu.y*260.*(1.-k*.5)+t*1.3+sin(iu.x*40.)*1.2),ring*.6)*.0016*(.4+k);
    c=textureLod(img,iu+w,0.).rgb;
    float spec=smoothstep(.55,.8,dot(c,vec3(.2,.5,.3)));
    c*=1.+spec*.5*(dn(vec2(iu.x*160.,iu.y*80.-t*1.5))-.4);
  }
  // spray mist rising where the falls hit the pool
  vec2 mp=(iu-vec2(.53,POOL+.02))*vec2(ia*1.6,3.5);
  float spray=exp(-dot(mp,mp)*4.)*mist(iu*vec2(ia,1.)+vec2(0.,-t*.03),vec2(0.,.05),5.);
  c=mix(c,vec3(.75,.95,.92),spray*.55);
  // light shafts from the opening, only in the far, open part of the cave
  float far=1.-smoothstep(.15,.4,d);
  float sh=shafts(iu,normalize(vec2(.18,-1.)),14.)*far*smoothstep(POOL,.7,iu.y);
  c+=vec3(.55,1.,.9)*sh*.13;
  fragColor=vec4(grain(c,.02),1.);
}
`,
    maps:"maps.png"
  },
  'evergreen': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
// Depth parallax from maps.r (white = near). The screen point s shows image point i where
// s = i + cam*(depth(i) - focal). Solve for i with a few fixed-point steps: near layers slide
// over far ones with no tearing, the way a real camera move would.
float depthAt(vec2 iu){return textureLod(maps,iu,1.).r;}
vec2 parallax(vec2 iu,vec2 cam,float focal){
  vec2 i=iu;
  for(int k=0;k<5;k++){ i=iu-cam*(depthAt(i)-focal); }
  return i;
}
// a slow, looping camera drift plus the pointer
vec2 camMove(float amp,float speed){
  vec2 auto_=vec2(sin(t*speed),sin(t*speed*.71+1.3)*.6)*amp;
  return auto_+(m-.5)*vec2(2.,1.4)*amp;
}
// mist: soft drifting banks. dir = drift direction, scale = bank size
float mist(vec2 p,vec2 dir,float scale){
  vec2 q=p*scale+dir*t;
  float n=dn(q)*.55+dn(q*2.1+vec2(3.1,1.7)-dir*t*.6)*.3+dn(q*4.3-dir*t*.3)*.15;
  return smoothstep(.35,.85,n);
}
// light shafts: soft streaks along \`dir\` (unit, image space), shimmering slowly
float shafts(vec2 p,vec2 dir,float freq){
  vec2 nrm=vec2(-dir.y,dir.x);
  float x=dot(p,nrm)*freq;
  float a=dn(vec2(x,t*.08))*.6+dn(vec2(x*2.3+5.,t*.11))*.4;
  return smoothstep(.45,.9,a);
}
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.08);
  iu=parallax(iu,camMove(.008,.1),.35);
  float d=depthAt(iu);
  // tree tops sway a touch (only the upper edges of crowns, more in the near trees)
  iu.x+=(dn(vec2(iu.x*20.,t*.35))-.5)*.0022*d*smoothstep(.25,.7,iu.y);
  vec3 c=textureLod(img,iu,0.).rgb;
  // mist banks drift through the layers, thicker where it's far (the background ridge)
  float far=1.-smoothstep(.2,.6,d);
  float m1=mist(vec2(iu.x*ia,iu.y),vec2(.03,.004),2.)*far;
  float m2=mist(vec2(iu.x*ia,iu.y)+7.,vec2(-.02,.002),3.4)*(1.-far)*smoothstep(.2,.55,iu.y);
  vec3 fog=vec3(.84,.9,.86);
  c=mix(c,fog,m1*.45+m2*.18);
  fragColor=vec4(grain(c,.018),1.);
}
`,
    maps:"maps.png"
  },
  'sunset-ridge': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
// Depth parallax from maps.r (white = near). The screen point s shows image point i where
// s = i + cam*(depth(i) - focal). Solve for i with a few fixed-point steps: near layers slide
// over far ones with no tearing, the way a real camera move would.
float depthAt(vec2 iu){return textureLod(maps,iu,1.).r;}
vec2 parallax(vec2 iu,vec2 cam,float focal){
  vec2 i=iu;
  for(int k=0;k<5;k++){ i=iu-cam*(depthAt(i)-focal); }
  return i;
}
// a slow, looping camera drift plus the pointer
vec2 camMove(float amp,float speed){
  vec2 auto_=vec2(sin(t*speed),sin(t*speed*.71+1.3)*.6)*amp;
  return auto_+(m-.5)*vec2(2.,1.4)*amp;
}
// mist: soft drifting banks. dir = drift direction, scale = bank size
float mist(vec2 p,vec2 dir,float scale){
  vec2 q=p*scale+dir*t;
  float n=dn(q)*.55+dn(q*2.1+vec2(3.1,1.7)-dir*t*.6)*.3+dn(q*4.3-dir*t*.3)*.15;
  return smoothstep(.35,.85,n);
}
// light shafts: soft streaks along \`dir\` (unit, image space), shimmering slowly
float shafts(vec2 p,vec2 dir,float freq){
  vec2 nrm=vec2(-dir.y,dir.x);
  float x=dot(p,nrm)*freq;
  float a=dn(vec2(x,t*.08))*.6+dn(vec2(x*2.3+5.,t*.11))*.4;
  return smoothstep(.45,.9,a);
}
// Two layers: a clean sky plate (sun + stars) that moves on its own, and the mountains from the photo.
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.08);
  vec2 cam=camMove(.012,.1);
  vec2 ip=parallax(iu,cam,.15);
  float land=textureLod(maps,ip,0.).g;                  // sharp ridge mask (G); depth stays in R
  // the sun sinks behind the ridge and rises again, slowly (seamless loop)
  float k=.5-.5*cos(t*.11);
  vec2 si=iu+cam*.15+vec2(0.,.07*k);
  vec3 sky=textureLod(sky,si,0.).rgb;
  // stars twinkle
  float dark=smoothstep(.16,.08,dot(sky,vec3(.33)));
  vec2 g=gl_FragCoord.xy/r.y*150.; vec2 id=floor(g),f=fract(g)-.5; float rnd=hash(id);
  sky+=vec3(1.,.95,.9)*smoothstep(.07,0.,length(f))*step(.975,rnd)*dark*(.45+.55*sin(t*(1.+rnd*3.)+rnd*30.))*.45;
  vec3 mtn=textureLod(img,ip,0.).rgb;
  // as the sun drops, the lit faces of the ridge cool down
  float warm=smoothstep(.04,.2,mtn.r-mtn.b);
  mtn*=1.-warm*.45*k;
  vec3 c=mix(sky,mtn,land);
  fragColor=vec4(grain(c,.02),1.);
}
`,
    maps:"maps.png",
    sky:"sky.jpg",
    skyPreview:"sky_s.jpg"
  },
  'orbit-ascii': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position=vec4(p,0.,1.); }`,
    frag:`#version 300 es
precision highp float;
uniform vec2 r,R,m,mv; uniform float t; uniform sampler2D prev;
out vec4 o;
// Ringed planet, ray-traced, for the ASCII engine. Banded atmosphere that rotates, a ring with gaps that
// casts its shadow onto the planet (and the planet onto the ring), terminator glow, twinkling stars.
float h21(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
float vn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  return mix(mix(h21(i),h21(i+vec2(1,0)),f.x),mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<4;i++){v+=a*vn(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}
mat3 rx(float a){float c=cos(a),s=sin(a);return mat3(1,0,0,0,c,-s,0,s,c);}
mat3 rz(float a){float c=cos(a),s=sin(a);return mat3(c,-s,0,s,c,0,0,0,1);}
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  float A=R.x/R.y;
  vec2 p=(uv-vec2(.62,.5))*vec2(A,1.);
  if(A<1.1) p=(uv-.5)*vec2(A,1.);
  p+=(m-.5)*.04;
  vec3 ro=vec3(0.,0.,4.6), rd=normalize(vec3(p,-1.75));
  mat3 tilt=rz(.42)*rx(-.22-(m.y-.5)*.12);
  vec3 L=normalize(vec3(-.55,.5,.85));
  float bright=0.; vec3 col=vec3(0.);
  // stars
  float st=step(.996,h21(floor(gl_FragCoord.xy)))*(.25+.35*(.5+.5*sin(t*2.+h21(floor(gl_FragCoord.xy)+3.)*40.)));
  bright=st*.5; col=vec3(.6,.65,.85);
  // planet
  float Rp=.82;
  float b=dot(ro,rd), c=dot(ro,ro)-Rp*Rp, h=b*b-c;
  float tP=1e9;
  if(h>0.) tP=-b-sqrt(h);
  // ring plane (in the tilted frame): y=0, radii 1.15..1.9
  vec3 rn=tilt*vec3(0.,1.,0.);
  float tR=-dot(ro,rn)/dot(rd,rn);
  vec3 rp=ro+rd*tR; float rr=length(rp);
  bool ring=tR>0.&&rr>1.15&&rr<1.92;
  float ringD=0.;
  if(ring){
    float band=.55+.45*sin(rr*38.)*sin(rr*11.+1.);
    band*=smoothstep(1.15,1.22,rr)*smoothstep(1.92,1.82,rr)*(1.-.85*smoothstep(.02,0.,abs(rr-1.52)));   // Cassini gap
    // planet shadow on the ring
    float bs=dot(rp,L), cs=dot(rp,rp)-Rp*Rp, hs=bs*bs-cs;
    float sh=(hs>0.&&-bs-sqrt(hs)>0.)?.12:1.;
    ringD=band*sh*(.55+.45*abs(dot(L,rn)));
  }
  if(tP<1e8&&(!ring||tP<tR)){
    vec3 q=ro+rd*tP, n=normalize(q);
    vec3 nl=transpose(tilt)*n;                                        // planet-local
    float lat=nl.y, lon=atan(nl.z,nl.x)+t*.12;
    float bands=fbm(vec2(lon*1.6,lat*9.+fbm(vec2(lon*3.,lat*14.)+t*.03)*1.4));
    float dif=max(dot(n,L),0.);
    // ring shadow on the planet
    float tr=-dot(q,rn)/dot(L,rn); vec3 rq=q+L*tr; float rl=length(rq);
    float rsh=(tr>0.&&rl>1.15&&rl<1.92)?.35+.4*(.5+.5*sin(rl*38.)):1.;
    float term=smoothstep(.0,.25,dif)*(1.-smoothstep(.25,.6,dif));
    bright=(dif*(.55+.6*bands)*rsh+term*.12);
    bright+=pow(1.-max(dot(n,-rd),0.),3.)*.35*smoothstep(-.2,.3,dot(n,L));   // atmosphere rim
    col=mix(vec3(1.,.55,.25),vec3(.95,.93,.88),smoothstep(.15,.6,dif));
    if(ring&&tR<tP) {}
  }
  if(ring&&tR<tP){ bright=max(bright*(1.-ringD*.4),ringD); col=mix(col,vec3(.9,.85,.75),.7); }
  o=vec4(col,clamp(bright,0.,1.));
}
`,
    glyph:`#version 300 es
precision highp float;
uniform sampler2D sc, at; uniform vec2 R, G; uniform float t, NG, CW, CH;
out vec4 o;
float h21(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
void main(){
  vec2 px=vec2(gl_FragCoord.x,R.y-gl_FragCoord.y);
  vec2 cell=floor(px/vec2(CW,CH)); vec2 f=fract(px/vec2(CW,CH));
  vec4 s=texelFetch(sc,ivec2(cell.x,G.y-1.-cell.y),0);
  float L=clamp(s.a,0.,1.);
  vec3 c;
  if(NG>0.){
    // a little life: a few cells re-roll one step up or down the ramp
    float j=h21(cell+floor(t*9.));
    float idx=clamp(floor(L*(NG-.01))+(j>.985?1.:j<.015?-1.:0.),0.,NG-1.);
    float g=texture(at,vec2((idx+f.x)/NG,f.y)).r;
    c=s.rgb*g;
  } else {
    // halftone: a round dot per cell, area proportional to brightness, rotated screen
    vec2 q=f-.5; q.x*=CW/CH;
    float rad=sqrt(L)*.62;
    float d=length(q);
    float aa=1.2/CH;
    c=s.rgb*smoothstep(rad+aa,rad-aa,d);
  }
  o=vec4(c,1.);
}`,
    kind:"ascii",
    glyphAtlas:"glyphs.png",
    glyphCount:27,
    stillTime:12,
    smoothing:0.12,
    previewScale:0.6,
    fallback:"radial-gradient(30% 40% at 62% 50%,#5a4a3a,#030304 70%)"
  },
  'twilight': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.06);
  iu.y-=.03*(.5+.5*sin(t*.06));                         // the glow slowly rises and settles
  iu=drift(iu,.03,.04);
  vec3 c=soft(iu,1.5);
  // pastel bands breathe: pinks warm and cool in a slow cycle
  float band=smoothstep(.05,.45,iu.y)*smoothstep(.75,.4,iu.y);
  c=mix(c,c*vec3(1.05,.97,1.03),band*(.5+.5*sin(t*.25)));
  // first stars at the top
  float dark=smoothstep(.65,.95,iu.y);
  vec2 g=gl_FragCoord.xy/r.y*170.; vec2 id=floor(g),f=fract(g)-.5; float rnd=hash(id);
  c+=vec3(1.,.96,.98)*smoothstep(.07,0.,length(f))*step(.975,rnd)*dark*(.45+.55*sin(t*(1.+rnd*3.)+rnd*30.))*.6;
  fragColor=vec4(grain(c,.018),1.);
}
`
  },
  'riptide': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.1+.02*sin(t*.05));
  iu=drift(iu,.07,.05);
  vec3 c=soft(iu,2.2);
  vec2 g=gl_FragCoord.xy+fract(t*11.)*137.;
  c+=(vec3(hash(g),hash(g+19.),hash(g+43.))-.5)*.07;
  fragColor=vec4(c,1.);
}
`
  },
  'seascape': {
    vert:`attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`,
    frag:`
precision highp float;
uniform vec2 r; uniform float t; uniform vec2 m;
// Raymarched ocean at golden hour: choppy octave waves (heightfield, bisection-refined), Fresnel sky
// reflection, subsurface colour on the wave crests, a sun glitter path, and a gradient sky with soft clouds.
float h21(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
float n2(vec2 p){vec2 i=floor(p),f=fract(p);vec2 u=f*f*(3.-2.*f);
  return -1.+2.*mix(mix(h21(i),h21(i+vec2(1,0)),u.x),mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),u.x),u.y);}
const mat2 OCT=mat2(1.6,1.2,-1.2,1.6);
float T;
float octave(vec2 uv,float choppy){
  uv+=n2(uv);
  vec2 wv=1.-abs(sin(uv)), swv=abs(cos(uv));
  wv=mix(wv,swv,wv);
  return pow(1.-pow(wv.x*wv.y,.65),choppy);
}
float sea(vec3 p,int iters){
  float freq=.16, amp=.6, choppy=4., h=0.;
  vec2 uv=p.xz; uv.x*=.75;
  for(int i=0;i<5;i++){
    if(i>=iters)break;
    float d=octave((uv+T)*freq,choppy)+octave((uv-T)*freq,choppy);
    h+=d*amp;
    uv*=OCT; freq*=1.9; amp*=.22; choppy=mix(choppy,1.,.2);
  }
  return p.y-h;
}
vec3 SUN;
vec3 skyc(vec3 e){
  float y=max(e.y,0.);
  vec3 c=mix(vec3(1.,.62,.36),vec3(.36,.5,.78),pow(y,.45));
  c=mix(c,vec3(.12,.2,.42),smoothstep(.25,1.,y));
  float s=max(dot(e,SUN),0.);
  c+=vec3(1.,.66,.36)*pow(s,6.)*.4+vec3(1.,.8,.55)*pow(s,120.)*.6+vec3(1.,.95,.85)*smoothstep(.99955,.9997,s)*4.;
  // soft cloud bands
  vec2 cp=e.xz/(e.y+.08);
  float cl=smoothstep(.1,.9,n2(cp*.6+vec2(t*.01,0.))*.5+n2(cp*1.4)*.3+.4)*smoothstep(.02,.18,e.y)*smoothstep(.6,.2,e.y);
  c=mix(c,mix(vec3(1.,.78,.65),vec3(.95,.55,.45),s),cl*.55);
  return c;
}
vec3 nrm(vec3 p,float eps){
  vec3 n; n.y=sea(p,5);
  n.x=sea(vec3(p.x+eps,p.y,p.z),5)-n.y;
  n.z=sea(vec3(p.x,p.y,p.z+eps),5)-n.y;
  n.y=eps;
  return normalize(n);
}
float trace(vec3 ori,vec3 dir,out vec3 p){
  float tm=0., tx=1000.;
  float hx=sea(ori+dir*tx,3);
  if(hx>0.){p=ori+dir*tx;return tx;}
  float hm=sea(ori,3), tmid=0.;
  for(int i=0;i<10;i++){
    tmid=mix(tm,tx,hm/(hm-hx));
    p=ori+dir*tmid;
    float hmid=sea(p,3);
    if(hmid<0.){tx=tmid;hx=hmid;}else{tm=tmid;hm=hmid;}
  }
  return tmid;
}
vec3 seaColor(vec3 p,vec3 n,vec3 l,vec3 eye,vec3 dist){
  float fr=clamp(1.-dot(n,-eye),0.,1.);
  fr=pow(fr,3.)*.65;
  vec3 refl=skyc(reflect(eye,n));
  vec3 base=vec3(0.,.09,.18), water=vec3(.8,.9,.6)*.6;
  vec3 refr=base+pow(dot(n,l)*.4+.6,80.)*water*.12;
  vec3 c=mix(refr,refl,fr);
  float atten=max(1.-dot(dist,dist)*.0004,.15);
  c+=water*(p.y-.6)*.18*atten;
  float spec=pow(max(dot(reflect(eye,n),l),0.),60.)*(60.+8.)/(3.14159*8.);
  c+=vec3(1.,.82,.6)*spec*.9*atten;
  return c;
}
void main(){
  T=1.+t*.8;
  vec2 uv=(gl_FragCoord.xy-.5*r)/r.y;
  SUN=normalize(vec3(.32+(m.x-.5)*.2,.045,-1.));
  float yaw=(m.x-.5)*.25, pitch=.085+(m.y-.5)*.06;
  vec3 ori=vec3(0.,3.4,-t*4.);   // sail forward (camera looks down -z)
  vec3 dir=normalize(vec3(uv,-2.));
  dir.z+=length(uv)*.14;
  dir=normalize(dir);
  float cy=cos(yaw),sy=sin(yaw),cp=cos(pitch),sp=sin(pitch);
  dir=vec3(dir.x,dir.y*cp-dir.z*sp,dir.y*sp+dir.z*cp);
  dir=vec3(dir.x*cy+dir.z*sy,dir.y,-dir.x*sy+dir.z*cy);
  vec3 p; trace(ori,dir,p);
  vec3 dist=p-ori;
  vec3 n=nrm(p,dot(dist,dist)*(.1/r.x));
  vec3 col=mix(skyc(dir),seaColor(p,n,SUN,dir,dist),pow(smoothstep(0.,-.02,dir.y),.2));
  // haze at the horizon
  col=mix(col,vec3(1.,.72,.5),exp(-abs(dir.y)*28.)*.35);
  col=pow(col,vec3(.75));
  vec2 q=gl_FragCoord.xy/r;
  col*=1.-.3*dot(q-.5,q-.5)*2.;
  col+=(h21(gl_FragCoord.xy+fract(t))-.5)*.012;
  gl_FragColor=vec4(col,1.);
}
`,
    kind:"procedural",
    context:"webgl",
    renderScale:0.7,
    previewScale:0.5,
    stillTime:20,
    smoothing:0.04,
    fallback:"linear-gradient(180deg,#e9b8a0,#f7c99a 55%,#ffd9a8 58%,#2b4363 60%,#0c1d33)"
  },
  'bokeh': {
    vert:`#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`,
    frag:`#version 300 es
precision highp float;
uniform sampler2D img;   // the scene image
uniform sampler2D maps;  // per-template maps (R = depth, white = near)
uniform sampler2D sky;   // optional clean background plate
uniform vec2 r;          // canvas size, px
uniform float t;         // seconds
uniform vec2 m;          // pointer 0..1, smoothed
uniform vec2 o;          // focus point in the image 0..1
uniform float ia;        // image aspect (w/h)
out vec4 fragColor;

// screen uv (0..1, y up) → image uv, cover-fit around focus o. zoom > 1 crops in a little,
// leaving margin so displacement/parallax never reveals an edge.
vec2 cover(vec2 uv,float zoom){
  float sa=r.x/r.y;
  vec2 s=sa>ia?vec2(1.,ia/sa):vec2(sa/ia,1.);
  s/=zoom;
  vec2 c=clamp(o,s*.5,1.-s*.5);
  return c+(uv-.5)*s;
}
float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
// Liquid drift for soft gradient photos: the image's own pixels flow along a slow, smooth field.
float dn(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*f*(f*(f*6.-15.)+10.);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
// curl of a noise potential → divergence-free flow (no pinching, looks like liquid)
vec2 curl(vec2 p){
  float e=.05;
  float n1=dn(p+vec2(0.,e)),n2=dn(p-vec2(0.,e)),n3=dn(p+vec2(e,0.)),n4=dn(p-vec2(e,0.));
  return vec2(n1-n2,-(n3-n4))/(2.*e);
}
// iu: image uv. amp ~ .02–.06, speed ~ .02–.06
vec2 drift(vec2 iu,float amp,float speed){
  float T=t*speed;
  vec2 q=iu*1.6;
  vec2 f=curl(q+vec2(T,T*.6))*.6+curl(q*2.1-vec2(T*.8,-T*1.1))*.4;
  iu+=f*amp*.18;
  // a second, slower sway of the whole field
  iu+=vec2(sin(T*1.3+iu.y*3.),cos(T*1.1+iu.x*2.5))*amp*.25;
  // pointer gently pushes the colour away
  vec2 mp=m; vec2 d=(gl_FragCoord.xy/r-mp)*vec2(r.x/r.y,1.);
  iu+=d*exp(-dot(d,d)*7.)*amp*.9;
  return iu;
}
// sample with optional blur (mip bias) — gradients with baked grain read cleaner blurred, then fresh grain on top
vec3 soft(vec2 iu,float lod){return textureLod(img,iu,lod*.2).rgb;}   // near-full detail: the image is the hero
vec3 grain(vec3 c,float amt){return c+(hash(gl_FragCoord.xy+fract(t*7.)*91.)-.5)*amt*.55;}   // light dither only
void main(){
  vec2 uv=gl_FragCoord.xy/r;
  vec2 iu=cover(uv,1.1);
  iu+=(m-.5)*.02;                                       // whole field leans with the pointer, like a lens pan
  iu=drift(iu,.06,.05);
  vec3 c=soft(iu,1.5);
  // the lights breathe: brighter patches swell and fade slowly
  float lum=dot(c,vec3(.3,.59,.11));
  float tw=dn(iu*4.+vec2(t*.12,-t*.09));
  c*=1.+.22*smoothstep(.25,.6,lum)*(tw-.45);
  fragColor=vec4(grain(c,.035),1.);
}
`
  }
};
