import {
  presentedBookPose,
  presentedYaw,
  type BookPose,
  type MotionLayout,
} from "./book-motion";

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function smooth(value: number) {
  const t = clamp01(value);
  return t * t * (3 - 2 * t);
}

function lerp(start: number, end: number, amount: number) {
  return start + (end - start) * amount;
}

/** Cover opens first, then the volume grows into the reader frame. */
const SPREAD_END = 0.34;
/** Early Z clearance overlaps the spread — mint-style forward push. */
const CLEARANCE_END = 0.42;

/** 0 = closed on shelf (presented), 1 = open reader frame. */
export function openTransitionPhases(progress: number) {
  const p = clamp01(progress);
  const spread = smooth(Math.min(1, p / SPREAD_END));
  const expand =
    p <= SPREAD_END ? 0 : smooth((p - SPREAD_END) / (1 - SPREAD_END));
  return {
    /** Cover swings open. */
    spread,
    /** Book grows toward the reader. */
    expand,
    /** Kept for callers that keyed off zoom — tied to expand. */
    zoom: expand,
  };
}

export function spreadCoverAngle(spread: number) {
  return spread * Math.PI * 0.52;
}

export type FocusedBookMotion = {
  x: number;
  z: number;
  yaw: number;
  scale: number;
  tiltX: number;
};

/**
 * Open path always starts from the presented pose (cover already facing camera).
 * Never re-animates shelved → presented yaw — that was the broken “re-unshelf.”
 */
export function focusedBookOpenPose(
  progress: number,
  layout: MotionLayout,
  focusZ: number,
  focusScale: number,
): FocusedBookMotion {
  const presented = presentedBookPose(layout);
  const { spread, expand } = openTransitionPhases(progress);
  const p = clamp01(progress);
  const clearance = smooth(Math.min(1, p / CLEARANCE_END));
  const grow = smooth(expand);

  return {
    x: 0,
    z: lerp(presented.z, focusZ, Math.max(clearance, grow)),
    yaw: presentedYaw,
    scale: lerp(presented.scale, focusScale, grow),
    tiltX: (1 - spread) * 0.012,
  };
}

/** Convenience for beginFocus — always snap to this before opening. */
export function focusOriginPose(layout: MotionLayout): BookPose {
  return presentedBookPose(layout);
}

export type PageScreenRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};
