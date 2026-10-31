/** ISO week helpers for stacking briefing shelves by week. */

export type WeekBucket = {
  /** e.g. "2026-W32" */
  key: string;
  /** Short label for UI, e.g. "This week" / "Aug 3–9" */
  label: string;
  /** Inclusive start ISO date of the week (Monday). */
  weekStart: string;
  bookIndices: number[];
  /** Scene Y for the shelf board under this week's books. */
  shelfY: number;
};

const MS_PER_DAY = 86_400_000;

function parseIsoDay(isoDate: string) {
  const parsed = new Date(`${isoDate}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Monday 00:00 local for the week containing `isoDate`. */
export function weekStartMonday(isoDate: string): Date {
  const date = parseIsoDay(isoDate) ?? new Date();
  const day = date.getDay(); // 0 Sun … 6 Sat
  const offset = day === 0 ? -6 : 1 - day;
  const monday = new Date(date.getTime() + offset * MS_PER_DAY);
  monday.setHours(12, 0, 0, 0);
  return monday;
}

export function isoWeekKey(isoDate: string): string {
  const monday = weekStartMonday(isoDate);
  const thursday = new Date(monday.getTime() + 3 * MS_PER_DAY);
  const year = thursday.getFullYear();
  const yearStart = new Date(year, 0, 1);
  const week = Math.ceil(
    ((thursday.getTime() - yearStart.getTime()) / MS_PER_DAY + 1) / 7,
  );
  return `${year}-W${String(week).padStart(2, "0")}`;
}

function formatDay(date: Date) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

function toIsoDay(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function weekLabel(weekStart: Date, todayIso?: string): string {
  const today = todayIso
    ? (parseIsoDay(todayIso) ?? new Date())
    : new Date();
  today.setHours(12, 0, 0, 0);
  const thisMonday = weekStartMonday(toIsoDay(today));
  const lastMonday = new Date(thisMonday.getTime() - 7 * MS_PER_DAY);
  const sunday = new Date(weekStart.getTime() + 6 * MS_PER_DAY);

  if (weekStart.getTime() === thisMonday.getTime()) return "This week";
  if (weekStart.getTime() === lastMonday.getTime()) return "Last week";
  return `${formatDay(weekStart)} – ${formatDay(sunday)}`;
}

/**
 * Group chronological volumes (newest-first) into shelf rows.
 * Newest row sits at shelfY = baseY; older rows step down.
 * `labelBuilder` lets hosts paint row-specific text on the shelf edge.
 */
export function buildWeekBuckets(
  dates: string[],
  options?: {
    rowPitch?: number;
    baseShelfY?: number;
    todayIso?: string;
    labelBuilder?: (weekStart: Date, weekIndex: number) => string;
  },
): WeekBucket[] {
  const rowPitch = options?.rowPitch ?? 2.55;
  const baseShelfY = options?.baseShelfY ?? 0.34;
  const todayIso = options?.todayIso;
  const labelBuilder = options?.labelBuilder;
  const order: string[] = [];
  const map = new Map<string, WeekBucket>();

  dates.forEach((date, index) => {
    const key = isoWeekKey(date);
    let bucket = map.get(key);
    if (!bucket) {
      const monday = weekStartMonday(date);
      bucket = {
        key,
        label: weekLabel(monday, todayIso),
        weekStart: toIsoDay(monday),
        bookIndices: [],
        shelfY: 0,
      };
      map.set(key, bucket);
      order.push(key);
    }
    bucket.bookIndices.push(index);
  });

  return order.map((key, weekIndex) => {
    const bucket = map.get(key)!;
    const monday = weekStartMonday(bucket.weekStart);
    return {
      ...bucket,
      label: labelBuilder
        ? labelBuilder(monday, weekIndex)
        : weekLabel(monday, todayIso),
      shelfY: baseShelfY - weekIndex * rowPitch,
    };
  });
}
