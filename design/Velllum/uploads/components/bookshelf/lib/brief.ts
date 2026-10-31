/** Daily brief types and display helpers (slimmed for the bookshelf demo). */

export const DAILY_BRIEF_TOOLKITS = [
  "gmail",
  "googlecalendar",
  "notion",
  "slack",
  "github",
] as const;

export const DAILY_BRIEF_TOOLKIT_NAMES: Record<string, string> = {
  gmail: "Gmail",
  googlecalendar: "Google Calendar",
  notion: "Notion",
  slack: "Slack",
  github: "GitHub",
};

export type BriefItemState =
  | "open"
  | "done"
  | "dismissed"
  | "unread"
  | "read";

export interface BriefSource {
  app_source: string;
  label?: string;
  external_id?: string;
  occurred_at?: string;
  toolkit_slug?: string;
  connection_id?: string;
  account_label?: string;
}

export interface BriefItem {
  id: string;
  title: string;
  description?: string;
  link?: string;
  app_source?: string;
  source?: BriefSource;
  state?: BriefItemState;
  start_at?: string;
  end_at?: string;
  timezone?: string;
  all_day?: boolean;
  location?: string;
  conference_url?: string;
  suggested_agent_ids?: string[];
  suggested_human_ids?: string[];
}

export interface BriefSection {
  id: string;
  kind: "tasks" | "bullets" | "updates" | "events" | string;
  title: string;
  items: BriefItem[];
}

export interface BriefDocument {
  schema_version: 1;
  type: "brief";
  brief_type?: string;
  date?: string;
  timezone?: string;
  title: string;
  description?: string;
  cover?: {
    image_url?: string;
    alt?: string;
    attribution?: string;
  };
  sections: BriefSection[];
  generation?: {
    previous_brief_id?: string | null;
    window_start?: string;
    window_end?: string;
    sources_checked?: string[];
    sources_unavailable?: string[];
  };
}

export interface BriefTaskStats {
  done: number;
  total: number;
}

/** Local `YYYY-MM-DD` — matches how briefs are keyed by calendar day. */
export function localBriefDate(date: Date = new Date()): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

const briefDayFormatter = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  month: "long",
  day: "numeric",
});

const briefDayWithYearFormatter = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  month: "long",
  day: "numeric",
  year: "numeric",
});

/** "Thursday, August 7" for an ISO brief date. Parsed at noon to avoid TZ drift. */
export function formatBriefDay(isoDate: string, today = new Date()): string {
  const parsed = new Date(`${isoDate}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.getFullYear() === today.getFullYear()
    ? briefDayFormatter.format(parsed)
    : briefDayWithYearFormatter.format(parsed);
}

/** "Today" / "Yesterday" for the two days that have one, else null. */
export function relativeBriefDay(
  isoDate: string,
  today = new Date(),
): "Today" | "Yesterday" | null {
  if (isoDate === localBriefDate(today)) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  return isoDate === localBriefDate(yesterday) ? "Yesterday" : null;
}

export function isBriefTaskComplete(item: BriefItem): boolean {
  return item.state === "done" || item.state === "dismissed";
}

/** Compact start time for event rows in summaries. */
export function formatBriefEventStart(
  item: BriefItem,
  briefTimezone?: string,
): string {
  if (item.all_day) return "All day";
  if (!item.start_at) return "—";
  const options: Intl.DateTimeFormatOptions = {
    hour: "numeric",
    minute: "2-digit",
  };
  const timezone = item.timezone || briefTimezone;
  if (timezone) options.timeZone = timezone;
  try {
    return new Intl.DateTimeFormat(undefined, options).format(
      new Date(item.start_at),
    );
  } catch {
    return "—";
  }
}

/** Counts completion in `kind: "tasks"` sections only. */
export function briefTaskStats(brief: BriefDocument): BriefTaskStats {
  let done = 0;
  let total = 0;
  for (const section of brief.sections) {
    if (section.kind !== "tasks") continue;
    for (const item of section.items) {
      total += 1;
      if (isBriefTaskComplete(item)) done += 1;
    }
  }
  return { done, total };
}
