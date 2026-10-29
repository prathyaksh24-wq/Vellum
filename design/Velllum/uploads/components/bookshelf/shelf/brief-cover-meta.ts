import type { BriefDocument } from "../lib/brief";
import { DAILY_BRIEF_TOOLKITS } from "../lib/brief";
import { normalizeAgentColor } from "../lib/agent-color";

export type CoverAgent = {
  id: string;
  name?: string;
  model?: string | null;
  agentColor?: string[];
  pictureUrl?: string | null;
};

export type BriefCoverSignals = {
  tools: string[];
  agentColors: string[];
  agents: CoverAgent[];
  tagline?: string;
  motif: BriefCoverMotif;
};

export type BriefCoverMotif =
  | "lattice"
  | "network"
  | "orbit"
  | "wave"
  | "schematic"
  | "continuum";

const MOTIFS: BriefCoverMotif[] = [
  "lattice",
  "network",
  "orbit",
  "wave",
  "schematic",
  "continuum",
];

function seeded(seed: string) {
  let state = 2166136261;
  for (const char of seed) {
    state ^= char.charCodeAt(0);
    state = Math.imul(state, 16777619);
  }
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function collectAgentIds(doc: BriefDocument) {
  const ids: string[] = [];
  for (const section of doc.sections) {
    for (const item of section.items) {
      if (item.suggested_agent_ids?.length) {
        ids.push(...item.suggested_agent_ids);
      }
    }
  }
  return unique(ids);
}

function collectTools(doc: BriefDocument) {
  const fromGeneration = doc.generation?.sources_checked ?? [];
  const fromItems = doc.sections.flatMap((section) =>
    section.items.flatMap((item) => {
      const slug = item.source?.toolkit_slug || item.app_source;
      return slug ? [slug.toLowerCase()] : [];
    }),
  );
  const merged = unique([...fromGeneration, ...fromItems].map((s) => s.toLowerCase()));
  return merged.filter((slug) =>
    (DAILY_BRIEF_TOOLKITS as readonly string[]).includes(slug),
  );
}

function motifForBrief(id: string, tools: string[]): BriefCoverMotif {
  if (tools.includes("github")) return "network";
  if (tools.includes("slack")) return "lattice";
  if (tools.includes("googlecalendar")) return "continuum";
  if (tools.includes("gmail")) return "wave";
  const random = seeded(id);
  return MOTIFS[Math.floor(random() * MOTIFS.length)] ?? "orbit";
}

export function extractBriefCoverSignals(
  doc: BriefDocument,
  agents: CoverAgent[],
): BriefCoverSignals {
  const tools = collectTools(doc);
  const agentIds = collectAgentIds(doc);
  const agentById = new Map(agents.map((agent) => [agent.id, agent]));
  const agentColors = unique(
    agentIds.flatMap((id) => normalizeAgentColor(agentById.get(id)?.agentColor)),
  );
  const featuredAgents = agentIds
    .slice(0, 5)
    .map((id) => agentById.get(id))
    .filter((agent): agent is CoverAgent => !!agent);

  return {
    tools,
    agentColors,
    agents: featuredAgents,
    tagline: doc.description?.trim().slice(0, 140) || undefined,
    motif: motifForBrief(doc.title || doc.date || "brief", tools),
  };
}
