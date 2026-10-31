/* Adapted from the user's supplied thinking-orbs component. Animation geometry,
 * state variants and timing are retained; TypeScript is removed for this entry. */
(()=>{
const { useEffect, useRef } = React;
const VARIANTS = {
  base: ["default"],
  working: ["default", "gyro"],
  reasoning: ["default", "twins"],
  searching: ["default", "lighthouse"],
  background: ["default", "spiral"],
  retrying: ["default", "surge"],
  compacting: ["default", "squeeze", "fuse"],
  waiting: ["default"]
};
const TAU = Math.PI * 2;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const ease = (x) => (1 - Math.cos(Math.PI * x)) / 2;
const hash = (n) => {
  const s = Math.sin(n * 127.1) * 43758.5453;
  return s - Math.floor(s);
};
const dist2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
const nearest = (pts, i, k) => {
  const idx = [], d = [], p = pts[i];
  for (let j = 0; j < pts.length; j++) {
    if (j === i) continue;
    const e = dist2(p, pts[j]);
    let at = idx.length;
    if (at === k) {
      if (e >= d[k - 1]) continue;
      at--;
    }
    while (at > 0 && d[at - 1] > e) {
      idx[at] = idx[at - 1];
      d[at] = d[at - 1];
      at--;
    }
    idx[at] = j;
    d[at] = e;
  }
  return idx;
};
const PERIOD = {
  base: 6500,
  working: 3e3,
  "working-gyro": 3e3,
  reasoning: 6500,
  "reasoning-twins": 6500,
  searching: 13e3,
  "searching-lighthouse": 13e3,
  background: 13e3,
  "background-spiral": 13e3,
  retrying: 13e3,
  "retrying-surge": 13e3,
  compacting: 1e4,
  "compacting-squeeze": 1e4,
  "compacting-fuse": 1e4,
  waiting: 13e3
};
const clocks = /* @__PURE__ */ new Map();
function tick(look, now, speed) {
  let c = clocks.get(look);
  if (!c) clocks.set(look, c = { t: 0, last: now });
  if (now > c.last) {
    c.t += Math.min(now - c.last, 100) * speed;
    c.last = now;
  }
  return c.t;
}
const spring = (x) => 1 - Math.exp(-4.5 * x) * Math.cos(3 * Math.PI * x) - x * Math.exp(-4.5);
function rewind(t, w) {
  const P = 3200, k = Math.floor(t / P), u = t - k * P;
  const back = 0.6 * 2100 * w;
  const fwd = (2e3 + 100 + 100) * w;
  let a;
  if (u < 2e3) a = u * w;
  else if (u < 2200) {
    const x = (u - 2e3) / 200;
    a = (2e3 + 200 * (x - x * x / 2)) * w;
  } else if (u < 3e3) a = 2100 * w - back * spring((u - 2200) / 800);
  else {
    const x = (u - 3e3) / 200;
    a = 2100 * w - back + 100 * x * x * w;
  }
  return k * (fwd - back) + a;
}
function yawOf(state, t) {
  if (state === "retrying") return rewind(2 * t, TAU / 9e3);
  if (state === "retrying-surge") {
    const turns = t / 3250, u = turns - Math.floor(turns);
    return (Math.floor(turns) + (1 - (1 - u) ** 3)) * TAU;
  }
  return t / PERIOD[state] * TAU;
}
const RING_AXIS = (() => {
  const tip = 30 * Math.PI / 180, roll = 10 * Math.PI / 180;
  return [-Math.sin(roll) * Math.cos(tip), Math.cos(roll) * Math.cos(tip), Math.sin(tip)];
})();
const TWIST = 1.4;
const LEAN = 30 * Math.PI / 180, TRAIL = Math.PI / 2;
const LENS_MS = 1800, MOVE = 0.4;
const LENS = 0.6;
function spot(k) {
  const phi = k * 2.45 + hash(k) * 1.5, theta = (15 + 30 * hash(k + 0.5)) * Math.PI / 180;
  return [Math.sin(theta) * Math.cos(phi), Math.sin(theta) * Math.sin(phi), Math.cos(theta)];
}
function lensAt(t) {
  const k = Math.floor(t / LENS_MS), u = t / LENS_MS - k;
  const e = u < MOVE ? (1 - Math.cos(u / MOVE * Math.PI)) / 2 : 1;
  const a = spot(k), b = spot(k + 1);
  const v = a.map((ai, j) => ai + (b[j] - ai) * e), n = Math.hypot(v[0], v[1], v[2]);
  return v.map((vi) => vi / n);
}
const HOP = 220, TAIL = 5, REACH = 24, WALK = 16;
const DOTS = {
  mount: ({ make, pts }) => {
    const els = pts.map(() => make("circle")), hidden = new Uint8Array(pts.length);
    return {
      dot(i, x, y, r, a) {
        const el = els[i], o = a.toFixed(2);
        if (o === "0.00" && hidden[i]) return;
        hidden[i] = +(o === "0.00");
        el.setAttribute("cx", x.toFixed(2));
        el.setAttribute("cy", y.toFixed(2));
        el.setAttribute("r", Math.max(0.45, r).toFixed(2));
        el.setAttribute("fill-opacity", o);
      }
    };
  }
};
function arms(count) {
  const at = (lat, lon) => [Math.cos(lat) * Math.cos(lon), Math.sin(lat), Math.cos(lat) * Math.sin(lon)];
  const g = Math.sqrt(4 * Math.PI / count), n = 8, along = 0.6 * g;
  return Array.from({ length: n }, (_, m) => {
    const room = m ? m & -m : n;
    const lim = Math.min(85 * Math.PI / 180, Math.acos(Math.min(1, g * n / (TAU * room))));
    const out = [];
    for (let lat = -lim + m * 0.618 % 1 * along; lat <= lim; lat += along / Math.sqrt(1 + Math.cos(lat) ** 2))
      out.push(at(lat, m / n * TAU - lat));
    return out;
  }).flat();
}
function distribute(state, count, shape) {
  if (shape) return shape.points(count, state);
  if (state === "background-spiral") return arms(count);
  return Array.from({ length: count }, (_, i) => {
    const y = 1 - 2 * (i + 0.5) / count, r = Math.sqrt(1 - y * y), th = i * GOLDEN;
    return [r * Math.cos(th), y, r * Math.sin(th)];
  });
}
function mountOrb(svg, { state: asked, variant, size = 20, speed = 1, label, shape, render = DOTS, density = 1, dotSize = 1, tilt = 20 } = {}) {
  const which = asked && Object.hasOwn(VARIANTS, asked) ? asked : "base";
  const own = variant !== "default" && VARIANTS[which].includes(variant ?? "");
  const state = own ? `${which}-${variant}` : which;
  const attrs = { width: size, height: size, viewBox: `0 0 ${size} ${size}`, fill: "currentColor" };
  for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, String(v));
  if (label) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
    svg.removeAttribute("aria-hidden");
  } else {
    svg.setAttribute("aria-hidden", "true");
    svg.removeAttribute("role");
    svg.removeAttribute("aria-label");
  }
  const dens = state === "background" ? 1 : 4;
  const count = Math.max(8, Math.round(size * dens * density));
  const form = typeof shape === "function" ? { points: shape } : shape;
  const c = size / 2, R = c * 0.8 * (form?.scale ?? 1), rs = (size / 64) ** 0.6 * (0.72 * Math.sqrt(4 / dens)) * dotSize;
  const pts = distribute(state, count, form);
  const make = (tag) => svg.appendChild(document.createElementNS("http://www.w3.org/2000/svg", tag));
  const drawer = render.mount({ make, pts, size, radius: rs }), flat = !!render.flat;
  const reasoning = (state === "reasoning" || state === "reasoning-twins") && pts.length > 1;
  const compacting = state === "compacting" || state === "compacting-fuse";
  const near = reasoning ? pts.map((_, i) => nearest(pts, i, REACH)) : [];
  const walks = Array.from({ length: state === "reasoning-twins" ? 2 : 1 }, () => []);
  let hops = 0;
  const draw = (t) => {
    const period = PERIOD[state], yaw = yawOf(state, t);
    const gyro = state === "working-gyro" ? t / 5e3 * TAU : null;
    const pitch = ((flat ? 0 : tilt) + (form?.tip ?? 0) + (gyro === null ? 0 : 10 * Math.cos(gyro))) * Math.PI / 180;
    const roll = gyro === null ? 0 : 12 * Math.sin(gyro) * Math.PI / 180, sr = Math.sin(roll), cr = Math.cos(roll);
    const sy = Math.sin(yaw), cy = Math.cos(yaw), st = Math.sin(pitch), ct = Math.cos(pitch);
    const facing = (k) => pts[k][1] * st + (-pts[k][0] * sy + pts[k][2] * cy) * ct;
    const lit = /* @__PURE__ */ new Map();
    if (reasoning) {
      const s = t / HOP, n = Math.floor(s), f = s - n;
      if (!walks[0].length) {
        const first = [...pts.keys()].reduce((b, k) => facing(k) > facing(b) ? k : b, 0);
        const apart = (k) => facing(k) + dist2(pts[k], pts[first]);
        walks.forEach((walk, w) => walk.push(w ? [...pts.keys()].reduce((b, k) => apart(k) > apart(b) ? k : b, 0) : first));
      }
      hops = Math.max(hops, n - WALK);
      for (; hops < n; hops++) {
        walks.forEach((walk, w) => {
          const recent = walk.slice(-8), from = walk[walk.length - 1];
          let best = -1, score = -Infinity;
          const other = state === "reasoning-twins" ? walks[1 - w].at(-1) : void 0;
          near[from].forEach((k, j) => {
            const apart = other === void 0 ? 0 : 1.2 * Math.min(Math.sqrt(dist2(pts[k], pts[other])), 0.8);
            const sc = facing(k) + 0.35 * hash(hops * 31 + j + w * 977) + apart;
            if (!recent.includes(k) && sc > score) {
              score = sc;
              best = k;
            }
          });
          walk.push(best < 0 ? near[from][0] : best);
          if (walk.length > WALK) walk.shift();
        });
      }
      const light = (k, v) => k !== void 0 && lit.set(k, Math.max(lit.get(k) ?? 0, v));
      for (const walk of walks)
        for (let j = TAIL - 1; j >= 0; j--) light(walk[walk.length - 1 - j], j === 0 ? ease(Math.min(1, f * 2)) : 1 - (j - 1 + f) / TAIL);
    }
    const head = t / 2e3 * TAU + yaw, ahead = TAU / 2e3 + TAU / period;
    const headLat = (tt) => 70 * Math.PI / 180 * (1 - 2 * (tt % 6e3 / 6e3));
    const glow = Math.min(1, 3 * Math.sin(Math.PI * (t % 6e3 / 6e3)));
    const lens = state === "searching" ? lensAt(t) : null;
    const tw = state === "working-gyro" ? 0.5 * Math.sin(t / 2600 * TAU) : state === "compacting-squeeze" ? Math.sin(t / 2600 * TAU) : 0;
    let sweep = null;
    if (compacting) {
      const u = t % 2800 / 2800, s = (u - 0.7) / 0.3;
      const release = state === "compacting-fuse" ? (1 - s) ** 3 : s < 0.45 ? 1 - 1.25 * ease(s / 0.45) : s < 0.7 ? -0.25 * (1 - (s - 0.45) / 0.25) ** 2 : 0;
      sweep = { at: -1.15 + 2.3 * Math.min(1, u / 0.7), hold: u < 0.7 ? 1 : release };
    }
    pts.forEach(([x, y, z], i) => {
      const turn = yaw + TWIST * tw * y;
      const [ly, lc] = tw ? [Math.sin(turn), Math.cos(turn)] : [sy, cy];
      const z1 = -x * ly + z * lc;
      let vx = x * lc + z * ly, vy = y * ct - z1 * st;
      const sx = z1, sy2 = vx * st;
      const vz = y * st + z1 * ct, d = (vz + 1) / 2;
      let r = (0.5 + 1.4 * d) * rs;
      let a = Math.max(0, (d - 0.3) / 0.7);
      if (lens) {
        const ang = Math.acos(Math.min(1, (vx * lens[0] + vy * lens[1] + vz * lens[2]) / Math.hypot(vx, vy, vz)));
        const w = ang < LENS ? (1 - (ang / LENS) ** 2) ** 2 : 0;
        a *= 1 - 0.55 * (1 - w);
        if (size <= 24) r *= 1 + 0.5 * w;
        if (w) {
          vx *= 1 + 0.12 * w;
          vy *= 1 + 0.12 * w;
          vx += (vx - lens[0]) * 0.35 * w;
          vy += (vy - lens[1]) * 0.35 * w;
          r *= 1 + 0.9 * w;
          a += (1 - a) * w;
        }
      }
      if (sweep) {
        const q = vx, w = Math.min(1, Math.max(0, (sweep.at - q) / 0.2)) * sweep.hold;
        const k = state === "compacting" ? 1.5 : 1;
        vx *= 1 - 0.2 * k * w;
        vy *= 1 - 0.2 * k * w;
        r *= 1 - 0.3 * k * w;
        if (state === "compacting-fuse") {
          a *= 1 - 0.5 * w;
          const g = Math.exp(-(((q - sweep.at) / 0.08) ** 2)) * Math.max(0, sweep.hold) * Math.min(1, d / 0.5);
          r *= 1 + 0.8 * g;
          a += (1 - a) * g;
        }
      }
      if (state === "working") {
        const u = t % 1700, at = 1.3 - 2.6 * ease(Math.min(1, u / 1200));
        const q = flat ? vy : vx * RING_AXIS[0] + vy * RING_AXIS[1] + vz * RING_AXIS[2];
        const g = u < 1200 ? Math.exp(-(((q - at) / 0.2) ** 2)) : 0;
        r *= 1 + 0.6 * g;
        a += (1 - a) * g;
        const w = Math.min(1, Math.max(0, (q - at) / 0.2)) * (u < 1200 ? 1 : 1 - Math.min(1, 1.6 * ((u - 1200) / 800)));
        vx *= 1 - 0.08 * w;
        vy *= 1 - 0.08 * w;
        r *= 1 - 0.15 * w;
      }
      if (state === "searching-lighthouse") {
        a *= 0.5;
        const lr = Math.sin(LEAN), lc2 = Math.cos(LEAN);
        const across = vx * lc2 - vy * lr, toward = -st * (vx * lr + vy * lc2) + ct * vz;
        const off = Math.atan2(across, toward) - (t / 2500 % 1 * TAU - Math.PI);
        const dphi = ((off + Math.PI) % TAU + TAU) % TAU - Math.PI;
        const beam = dphi < 0 ? Math.max(0, 1 + dphi / TRAIL) : Math.exp(-((dphi / 0.45) ** 2));
        const g = beam * (0.25 + 0.75 * Math.min(1, Math.max(0, (d - 0.4) / 0.3)));
        r *= 1 + 0.6 * g;
        a += (1 - a) * g;
      }
      if (reasoning) {
        const spark = lit.get(i) ?? 0;
        a *= 0.5;
        if (spark) {
          r *= 1 + 0.8 * spark;
          a += (1 - a) * spark;
        }
      }
      if (state === "waiting") {
        const lat = Math.asin(y / (Math.hypot(x, y, z) || 1)), lon = Math.atan2(z, x);
        const off = Math.atan2(Math.sin(lon - head), Math.cos(lon - head)), along = off * Math.cos(lat);
        const g = Math.exp(-(((lat - headLat(t + off / ahead)) / 0.28) ** 2)) * Math.exp(-((along / (off * ahead > 0 ? 0.12 : 1)) ** 2));
        const w = glow * g ** 0.6;
        a = a * 0.5 + (1 - a * 0.5) * w;
        r *= 1 + 1.1 * w;
      }
      if (roll) [vx, vy] = [vx * cr - vy * sr, vx * sr + vy * cr];
      drawer.dot(i, c + vx * R, c - vy * R, r, a, sx, -sy2);
    });
    drawer.frame?.();
  };
  const look = `${state}@${speed}`;
  draw(tick(look, performance.now(), speed));
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let visible = true, raf = 0, dead = false, paused = false;
  const canAnimate = () => !dead && !paused && visible && !document.hidden && !motion.matches;
  function frame(now) {
    raf = 0;
    if (!canAnimate()) return;
    draw(tick(look, now, speed));
    raf = requestAnimationFrame(frame);
  }
  const sync = () => {
    if (!canAnimate()) { cancelAnimationFrame(raf); raf = 0; }
    else if (!raf) raf = requestAnimationFrame(frame);
  };
  const pause = () => { paused = true; sync(); };
  const play = () => { paused = false; sync(); };
  const io = new IntersectionObserver(es => { visible = es[es.length - 1].isIntersecting; sync(); });
  io.observe(svg);
  motion.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  play();
  return {
    pause,
    play,
    destroy() {
      dead = true;
      pause();
      io.disconnect();
      motion.removeEventListener('change', sync);
      document.removeEventListener('visibilitychange', sync);
      svg.replaceChildren();
    }
  };
}
function Orb({
  state,
  variant,
  size = 20,
  speed = 1,
  paused = false,
  label,
  shape,
  render,
  density,
  dotSize,
  tilt,
  className
}) {
  const ref = useRef(null);
  const orb = useRef(null);
  useEffect(() => {
    const o = orb.current = mountOrb(ref.current, { state, variant, size, speed, label, shape, render, density, dotSize, tilt });
    return o.destroy;
  }, [state, variant, size, speed, label, shape, render, density, dotSize, tilt]);
  useEffect(() => {
    if (paused) orb.current.pause();
    else orb.current.play();
  }, [paused, state, variant, size, speed, label, shape, render, density, dotSize, tilt]);
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true };
  return <svg ref={ref} width={size} height={size} viewBox={`0 0 ${size} ${size}`} fill="currentColor" className={className} {...a11y} />;
}

window.VellumUI=window.VellumUI || {};
window.VellumUI.ThinkingOrb=Orb;
})();
