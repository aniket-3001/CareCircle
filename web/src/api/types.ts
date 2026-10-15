// Shapes returned by the Care Circle API (graphmem/care.py, care_view.py, carecircle/checks.py, intake.py).

export interface Session {
  circle: string;
  person: string;
  keys: Record<string, string>; // agent name -> API key
  as: string; // which agent is acting
}

export interface RegimenEntry {
  id: string;
  drug: string;
  dose_text: string;
  freq_text: string;
  since: number;
  source: 'typed' | 'photo' | 'voice' | 'document';
  quote: string;
  by: string;
}

export interface DirectFlag {
  kind: 'direct';
  drugs: [string, string];
  level: string;
  source: string;
  weight?: number;
}

export interface EnzymePath {
  kind: 'enzyme_path';
  path: string;
  meaning: string;
  weight: number;
  also_in_ddinter: boolean;
  source: string;
  x: string;
  y: string;
  enzyme: string;
  relation: 'INHIBITS' | 'INDUCES';
  strength: string;
}

export interface Judgement {
  state: 'no_data' | 'partial' | 'flags' | 'no_known_conflict';
  reasons: string[];
  statement: string;
}

export interface CheckResult {
  checked: string[];
  not_in_reference: string[];
  direct: DirectFlag[];
  unrated: DirectFlag[];
  enzyme_paths: EnzymePath[];
  regimen_risk: number | null;
  notice: string;
  regimen: RegimenEntry[];
  judgement: Judgement;
}

export interface Unacknowledged {
  dose: string;
  drug: string;
  action: string;
  age_hours: number;
}

export interface Divergence {
  carers: Record<string, { unacknowledged: Unacknowledged[]; divergence: number }>;
  most_out_of_date: string | null;
  half_life_hours: number;
  weights_are_assumptions: boolean;
}

export interface Nudge {
  kind: 'remind' | 'escalate';
  about_carer: string;
  notify: string;
  drug: string;
  age_hours: number;
  message: { text: string };
}

export interface Candidate {
  name: string;
  score: number;
}

export interface Proposal {
  drug_candidates: Candidate[];
  dose_text: string;
  freq_text: string;
  quote: string;
  method: string;
  verified: boolean;
  needs_human: boolean;
}

export interface IntakeResult {
  source: { kind: string; method: string; status: string; note: string | null };
  text: string;
  proposals: Proposal[];
}

export interface GiveRecord {
  drug: string;
  slot: string;
  by: string;
  at: number;
}

export interface GiveResult {
  given: boolean;
  duplicate?: boolean;
  already_given_by?: string;
  note?: string;
}

export interface HubRow {
  drug: string;
  score?: number;
  hazards_in_regimen?: number;
  weight?: number;
}

export interface Hubs {
  regimen_hubs: { cypher: string; rows: HubRow[] };
  global_hubs: { cypher: string; rows: HubRow[] };
}

export type Meta = [string, string][];

export type NodeKind = 'patient' | 'carer' | 'dose' | 'dose_old' | 'drug' | 'drug_old' | 'enzyme';
export type EdgeKind = 'for' | 'of' | 'recorded' | 'acked' | 'supersedes' | 'interacts' | 'inhibits' | 'induces' | 'substrate';

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  summary: string;
  meta: Meta;
  cypher: string;
  current?: boolean;
  at?: number;
  score?: number;
  rank?: number | null;
  short?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  label: string;
  summary: string;
  meta: Meta;
  level?: string;
  weight?: number;
  weak?: boolean;
}

export interface CareGraph {
  person: string;
  now: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  judgement: Judgement;
  legend: Record<string, string>;
  notice: string;
}

export interface TimelineEvent {
  at: number;
  kind: 'record' | 'stop' | 'ack' | 'give' | 'forget';
  dose?: string;
  who: string;
  text: string;
  quote: string;
  when: string;
  ago: string;
}

export interface Receipt {
  receipt: string;
  kind: string;
  sha256: string;
  at: number;
  when: string;
  by: string;
  reason: string;
  removed: string;
}

export interface FhirBundle {
  resourceType: 'Bundle';
  entry: { resource: { resourceType: string } }[];
}

export interface People {
  patients: string[];
  carers: string[];
}
