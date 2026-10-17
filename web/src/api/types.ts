// Shapes returned by the Care Circle API (graphmem/care.py, care_view.py, carecircle/checks.py, intake.py).

/** What this browser holds. For a signed-in account `keys` is just `{ me: <session token> }` and everything else is read from the server. */
export interface Session {
  circle: string; // '' when an account has no circle yet
  person: string;
  keys: Record<string, string>; // agent name -> bearer token (API key for the anonymous demo, session token for an account)
  as: string; // which agent is acting
  account?: { provider: 'local' | 'cognito'; tokens?: import('../lib/cognito').Tokens };
  demoCircle?: boolean; // the throw-away anonymous demo: unlocks demo-only tools
}

export interface RegimenEntry {
  product?: string;
  slots?: string[];
  as_needed?: boolean;
  ends_on?: string | null;
  id: string;
  drug: string;
  dose_text: string;
  freq_text: string;
  since: number;
  source: 'typed' | 'photo' | 'voice' | 'document';
  quote: string;
  by: string;
}

export interface Suggestion {
  times: string[];
  label: string;
  as_needed: boolean;
  ends_in_days: number | null;
  understood: boolean;
  why: string;
}

export interface TodayItem {
  dose_id: string;
  drug: string;
  dose_text: string;
  freq_text: string;
  time: string;
  slot: string;
  at: number;
  state: 'given' | 'due' | 'not_marked' | 'upcoming';
  given_by: string | null;
  given_at: number | null;
  needs_second_carer: boolean;
}

export interface EntrySource {
  id: string;
  how_entered: string;
  quote: string;
  has_source: boolean;
  kind: string | null;
  text: string;
  sha256: string | null;
  read_at: number | null;
  note: string;
}

export interface Outcomes {
  days: number;
  from: string;
  to: string;
  tz: string;
  doses_due: number;
  doses_marked_given: number;
  doses_not_marked: number;
  entries_recorded: number;
  entries_marked_mistake: number;
  flagged_now: number;
  possible_duplicates_now: number;
  changes_not_yet_seen: number;
  note: string;
}

export interface ConsentEntry { id: string; status: 'agreed' | 'declined' | 'not_asked'; who: string; note: string; by: string; at: number }
export interface ConsentView { status: ConsentEntry['status']; current: ConsentEntry | null; history: ConsentEntry[]; note: string }
export interface PatientView {
  person: string;
  medicines: { drug: string; dose_text: string; freq_text: string; slots: string[]; recorded_by: string }[];
  who_can_see: string[];
  what_is_kept: string[];
  what_is_not: string[];
  your_rights: string;
  consent: ConsentEntry | null;
}

export interface StockRow {
  dose_id: string;
  drug: string;
  doses_left: number;
  counted: number;
  counted_at: number;
  per_day: number;
  days_left: number | null;
  runs_out_on: string | null;
}

export interface TodayView {
  person: string;
  tz: string;
  date: string;
  items: TodayItem[];
  counts: { given: number; due: number; not_marked: number; upcoming: number };
  unscheduled: { dose_id: string; drug: string; dose_text: string; freq_text: string; suggestion: Suggestion }[];
  as_needed: { dose_id: string; drug: string; dose_text: string; freq_text: string }[];
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
  headline?: string;
  state: 'no_data' | 'partial' | 'flags' | 'no_known_conflict';
  reasons: string[];
  statement: string;
}

export interface DuplicateFlag {
  kind: 'duplicate';
  ingredient: string;
  entries: { id: string; product: string; dose_text: string; freq_text: string; by: string }[];
  meaning: string;
  source: string;
}

export interface CheckResult {
  checked: string[];
  not_in_reference: string[];
  direct: DirectFlag[];
  unrated: DirectFlag[];
  enzyme_paths: EnzymePath[];
  duplicates?: DuplicateFlag[];
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

export interface Reminder extends Nudge {
  delivered: boolean;
}

export interface Candidate {
  name: string;
  score: number;
  /** Not in the reference data: it can be recorded, but nothing is checked for it. */
  unchecked?: boolean;
  via?: string;
}

export interface Proposal {
  drug_candidates: Candidate[];
  dose_text: string;
  freq_text: string;
  quote: string;
  method: string;
  verified: boolean;
  needs_human: boolean;
  /** Set when the text named a combination product (Telma-AM): one proposal is made for each ingredient. */
  combination?: string;
  combination_ingredients?: string[];
  combination_strength?: string;
}

export interface IntakeResult {
  source: { kind: string; method: string; status: string; note: string | null };
  source_id?: string;
  text: string;
  proposals: Proposal[];
}

export interface FollowupSuggestion { key: string; kind: string; text: string; basis: string[] }
export interface Followup { id: string; text: string; kind: string; status: 'open' | 'done'; by: string; at: number; done_by: string | null; done_at: number | null; stale: boolean }

export interface Counts {
  reading: { saved: number; unchanged: number; statement: string };
  load: { medicines: number; times_of_day: number; special_directions: number; statement: string };
  anticholinergic: { total: number; medicines: { drug: string; score: number }[]; source: string; statement: string };
  coverage: { statement: string; rated: number; unrated: number; not_listed: number; pairs_possible: number };
  note: string;
}
export interface Handover { id: string; text: string; by: string; at: number }
export interface GiveRecord {
  witness?: string | null;
  needs_second_carer?: boolean;
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

/** The graph-algorithm operations on a circle's own graph (graphmem/graph_algos.py). A node is named by its label and ref. */
export interface GNode { label: string; ref: string; title: string }
export interface Unlinked { records: number; of: number }
export interface GInfluence { metric: string; label: string | null; rows: (GNode & { score: number })[]; computed_by: string; cypher: string; note?: string; unlinked?: Unlinked }
export interface GCommunities { method: string; groups: { group: number; size: number; kinds: Record<string, number>; sample: GNode[] }[]; nodes_in_graph: number; cypher: string; note?: string; unlinked?: Unlinked }
export interface GPath { found: boolean; reason?: string; length?: number; path: GNode[]; relationships?: string[]; cypher?: string }

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
  kind: 'record' | 'stop' | 'ack' | 'give' | 'forget' | 'mistake';
  dose?: string;
  status?: 'confirmed' | 'pending' | 'mistake';
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

// ---- accounts, circles, assistant
export interface AuthConfig {
  provider: 'local' | 'cognito';
  cognito: { region: string; userPoolId: string; clientId: string } | null;
  demo_accounts: { email: string; name: string; password: string }[];
  password_rule: string;
}

export interface Account {
  id: string;
  email: string;
  name: string;
  provider: 'local' | 'cognito';
  demo: boolean;
  created_at: number;
}

export interface ShareLink { id: string; token: string; path: string; expires_at: number; hours: number; note: string }
export interface ShareRow { id: string; created: number; expires_at: number; views: number; revoked: boolean; active: boolean; note: string }
export interface Review { id: string; name: string; note: string; at: number; verified: boolean }

export interface CircleInfo {
  id: string;
  name: string;
  person: string;
  role: 'owner' | 'carer';
  members: number;
  demo: boolean;
}

export interface Profile extends Account {
  circles: CircleInfo[];
  telegram: { chat: number; circle: string }[];
}

export interface Member {
  id: string;
  name: string;
  role: 'owner' | 'carer';
  since: number;
  you: boolean;
}

export interface Invite {
  code: string;
  expires_at: number;
  hours: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  at: number;
  source: string;
  links: { tab: string; label: string }[];
  proposals: Proposal[];
  proposal_text?: string;
  left_today?: number;
}

export interface DrugInfo {
  drug: string;
  in_interaction_reference: boolean;
  rxnorm: { name: string; rxcui: string; source: string } | null;
  label: { boxed_warning: string; indications: string; effective: string; brand: string; url: string; source: string } | null;
  available: boolean;
  note: string;
}

export interface Recall { drug: string; number: string; class: string; firm: string; reason: string; product: string; reported: string; source: string }
export interface Recalls { checked: string[]; available: boolean; recalls: Recall[]; note: string }
export interface SoleKnowers { carers: string[]; sole: { dose: string; drug: string; only: string; since: number }[]; keystone: string | null; keystone_count: number }

export interface Reading { id: string; kind: string; label: string; value: number; unit: string; at: number; by: string; note: string }
export interface Trend {
  kind: string; label: string; units: string[]; series: Reading[]; drug: string; window_days: number; note: string;
  changes: { dose: string; at: number; action: string; text: string; before: { n: number; mean: number | null }; after: { n: number; mean: number | null } }[];
}

export interface Appointment { id: string; title: string; at: number; place: string; who: string; bring: string; by: string; status: 'upcoming' | 'done' | 'cancelled' }
export interface CareProfile { conditions: { id: string; name: string; by: string }[]; allergies: { id: string; text: string; drug: string; by: string }[] }
export interface AllergyCheck { hits: { allergy: string; drug: string; entry: string; why: string }[]; allergies: number; note: string }
export interface Visit {
  appointment: Appointment | null; since: number; note: string;
  changes: { drug: string; action: string; dose_text: string; freq_text: string; at: number; by: string; source: string }[];
  readings: { kind: string; value: number; unit: string; at: number }[];
  flags: { drugs?: string[]; level?: string; path?: string; source: string }[];
  unseen: Record<string, { drug: string; age_hours: number }[]>;
  allergy_hits: AllergyCheck['hits'];
  regimen: RegimenEntry[];
}
