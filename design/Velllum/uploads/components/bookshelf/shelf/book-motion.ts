export type BookPose = {
  x: number;
  z: number;
  yaw: number;
  scale: number;
};

export type BookFootprint = BookPose & {
  id: string;
  width: number;
  thickness: number;
};

export type MotionBookSize = {
  width: number;
  thickness: number;
};

export type MotionLayout = {
  shelvedZ: number;
  presentedZ: number;
  rotationLaneZ: number;
  presentedScale: number;
  collisionMargin: number;
};

export type BrowseMotionPhase =
  | "retreat-current"
  | "turn-current"
  | "shelve-current"
  | "extract-next"
  | "turn-next"
  | "settle-next"
  | "present-from-peek";

export const shelvedYaw = Math.PI / 2;
export const presentedYaw = 0;

const shelvedZ = -0.64;
const presentedZ = 0.4;
const presentedScale = 1.035;
const maximumFocusScale = 1.08;
const collisionMargin = 0.035;

export const browsePhaseDuration: Record<BrowseMotionPhase, number> = {
  "retreat-current": 0.11,
  "turn-current": 0.14,
  "shelve-current": 0.13,
  "extract-next": 0.13,
  "turn-next": 0.14,
  "settle-next": 0.11,
  "present-from-peek": 0.12,
};

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

export function createMotionLayout(books: MotionBookSize[]): MotionLayout {
  const maxShelvedHalfDepth = books.reduce(
    (maximum, book) => Math.max(maximum, book.width * 0.5),
    0,
  );
  const maxRotationRadius = books.reduce(
    (maximum, book) =>
      Math.max(
        maximum,
        Math.hypot(book.width, book.thickness) * 0.5 * maximumFocusScale,
      ),
    0,
  );

  return {
    shelvedZ,
    presentedZ,
    rotationLaneZ:
      shelvedZ + maxShelvedHalfDepth + maxRotationRadius + collisionMargin,
    presentedScale,
    collisionMargin,
  };
}

export function shelvedBookPose(layout: MotionLayout): BookPose {
  return {
    x: 0,
    z: layout.shelvedZ,
    yaw: shelvedYaw,
    scale: 1,
  };
}

export function presentedBookPose(layout: MotionLayout): BookPose {
  return {
    x: 0,
    z: layout.presentedZ,
    yaw: presentedYaw,
    scale: layout.presentedScale,
  };
}

/** Partial pull-forward while scrolling — spine stays mostly visible. */
export function scrollLiftPose(
  lift: number,
  layout: MotionLayout,
): BookPose {
  const t = smooth(lift);
  const peekZ =
    layout.shelvedZ + (layout.presentedZ - layout.shelvedZ) * 0.48;
  const peekYaw = lerp(shelvedYaw, presentedYaw, t * 0.18);
  const peekScale = lerp(1, layout.presentedScale, t * 0.28);

  return {
    x: 0,
    z: lerp(layout.shelvedZ, peekZ, t),
    yaw: lerp(shelvedYaw, peekYaw, t),
    scale: peekScale,
  };
}

export function scrollProximityLift(
  bookIndex: number,
  scrollIndex: number,
  radius = 0.92,
) {
  const dist = Math.abs(bookIndex - scrollIndex);
  return smooth(1 - clamp01(dist / radius));
}

export function peekToPresentedPose(
  progress: number,
  layout: MotionLayout,
  fromLift = 1,
): BookPose {
  const from = scrollLiftPose(fromLift, layout);
  const to = presentedBookPose(layout);
  const t = smooth(progress);
  return {
    x: lerp(from.x, to.x, t),
    z: lerp(from.z, to.z, t),
    yaw: lerp(from.yaw, to.yaw, t),
    scale: lerp(from.scale, to.scale, t),
  };
}

export function browseMotionPose(
  phase: BrowseMotionPhase,
  progress: number,
  layout: MotionLayout,
): BookPose {
  const t = smooth(progress);

  switch (phase) {
    case "retreat-current":
      return {
        x: 0,
        z: lerp(layout.presentedZ, layout.rotationLaneZ, t),
        yaw: presentedYaw,
        scale: lerp(layout.presentedScale, 1, t),
      };
    case "turn-current":
      return {
        x: 0,
        z: layout.rotationLaneZ,
        yaw: lerp(presentedYaw, shelvedYaw, t),
        scale: 1,
      };
    case "shelve-current":
      return {
        x: 0,
        z: lerp(layout.rotationLaneZ, layout.shelvedZ, t),
        yaw: shelvedYaw,
        scale: 1,
      };
    case "extract-next":
      return {
        x: 0,
        z: lerp(layout.shelvedZ, layout.rotationLaneZ, t),
        yaw: shelvedYaw,
        scale: 1,
      };
    case "turn-next":
      return {
        x: 0,
        z: layout.rotationLaneZ,
        yaw: lerp(shelvedYaw, presentedYaw, t),
        scale: 1,
      };
    case "settle-next":
      return {
        x: 0,
        z: lerp(layout.rotationLaneZ, layout.presentedZ, t),
        yaw: presentedYaw,
        scale: lerp(1, layout.presentedScale, t),
      };
    case "present-from-peek":
      return peekToPresentedPose(progress, layout);
  }
}

export function focusedBookPose(
  progress: number,
  layout: MotionLayout,
  focusX: number,
  focusZ: number,
  focusScale: number,
): BookPose {
  const value = Math.min(1, Math.max(0, progress));
  const clearanceProgress = smooth(Math.min(1, value / 0.55));
  const presentationProgress = smooth(Math.max(0, (value - 0.55) / 0.45));

  return {
    x: lerp(0, focusX, presentationProgress),
    z: lerp(layout.presentedZ, focusZ, clearanceProgress),
    yaw: presentedYaw,
    scale: lerp(layout.presentedScale, focusScale, presentationProgress),
  };
}

type Axis = { x: number; z: number };

function dot(left: Axis, right: Axis) {
  return left.x * right.x + left.z * right.z;
}

function axesFor(footprint: BookFootprint) {
  const cosine = Math.cos(footprint.yaw);
  const sine = Math.sin(footprint.yaw);
  return {
    width: { x: cosine, z: -sine },
    thickness: { x: sine, z: cosine },
  };
}

export function bookFootprintsOverlap(
  left: BookFootprint,
  right: BookFootprint,
  margin = collisionMargin,
) {
  const leftAxes = axesFor(left);
  const rightAxes = axesFor(right);
  const axes = [
    leftAxes.width,
    leftAxes.thickness,
    rightAxes.width,
    rightAxes.thickness,
  ];
  const centerDelta = {
    x: right.x - left.x,
    z: right.z - left.z,
  };
  const leftHalfWidth = left.width * left.scale * 0.5 + margin * 0.5;
  const leftHalfThickness =
    left.thickness * left.scale * 0.5 + margin * 0.5;
  const rightHalfWidth = right.width * right.scale * 0.5 + margin * 0.5;
  const rightHalfThickness =
    right.thickness * right.scale * 0.5 + margin * 0.5;

  return axes.every((axis) => {
    const distance = Math.abs(dot(centerDelta, axis));
    const leftRadius =
      leftHalfWidth * Math.abs(dot(leftAxes.width, axis)) +
      leftHalfThickness * Math.abs(dot(leftAxes.thickness, axis));
    const rightRadius =
      rightHalfWidth * Math.abs(dot(rightAxes.width, axis)) +
      rightHalfThickness * Math.abs(dot(rightAxes.thickness, axis));
    return distance < leftRadius + rightRadius;
  });
}
