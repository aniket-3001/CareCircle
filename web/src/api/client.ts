import type { Review, ShareLink, ShareRow, ConsentView, PatientView, Outcomes, EntrySource, Candidate, StockRow, Counts, Followup, FollowupSuggestion, Handover, AllergyCheck, Appointment, CareProfile, Visit, DrugInfo, Reading, Trend, Recalls, SoleKnowers,
  Account, AuthConfig, CareGraph, ChatMessage, CheckResult, Divergence, FhirBundle, GiveRecord, GiveResult, Hubs, GInfluence, GCommunities, GPath, IntakeResult, Invite, Member, Reminder, People,
  Profile, Receipt, RegimenEntry, Session, TimelineEvent, CircleInfo, TodayView,
} from './types';

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function parse<T>(r: Response): Promise<T> {
  const j = (await r.json().catch(() => ({}))) as { result?: T; detail?: unknown; error?: string };
  if (!r.ok) {
    const d = typeof j.detail === 'string' ? j.detail : j.error;
    throw new ApiError(d ?? r.statusText ?? 'request failed', r.status);
  }
  return (j.result ?? (j as unknown)) as T;
}

const bearer = (token: string) => ({ 'content-type': 'application/json', authorization: `Bearer ${token}` });
/** A 401 on a request that carried a token means the session has ended (signed out elsewhere, password changed, expired): tell the app once, so it can go back to sign-in. */
const ended = (r: Response): Response => {
  if (r.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('cc-session-ended'));
  return r;
};
const get = <T>(path: string, token: string) => fetch(path, { headers: bearer(token) }).then((r) => parse<T>(ended(r)));
const send = <T>(method: string, path: string, token: string, body?: unknown) =>
  fetch(path, { method, headers: bearer(token), body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => parse<T>(ended(r)));

/** The circle operations for one signed-in carer: every call carries that carer's token, so the server checks their grants on each query. */
export function apiFor(s: Session) {
  const token = s.keys[s.as] ?? '';
  const base = `/v1/tenants/${encodeURIComponent(s.circle)}`;
  const op = <T>(name: string, args: Record<string, unknown> = {}) => send<T>('POST', `${base}/${name}`, token, args);
  const p = s.person;
  return {
    check: (as_of?: number) => op<CheckResult>('care_check', { person: p, ...(as_of === undefined ? {} : { as_of }) }),
    regimen: (as_of?: number) => op<RegimenEntry[]>('care_regimen', { person: p, ...(as_of === undefined ? {} : { as_of }) }),
    drugInfo: (drug: string) => op<DrugInfo>('care_drug_info', { drug }),
    recalls: () => op<Recalls>('care_recalls', { person: p }),
    soleKnowers: () => op<SoleKnowers>('care_sole_knowers', { person: p }),
    measure: (kind: string, value: number, unit: string, at?: number) => op<Reading>('care_measure', { person: p, kind, value, unit, ...(at ? { at } : {}) }),
    measures: (kind = '') => op<Reading[]>('care_measures', { person: p, kind, limit: 200 }),
    forgetMeasure: (id: string) => op<{ removed: string }>('care_forget_measure', { measure_id: id }),
    trend: (kind: string, drug = '', now = Date.now()) => op<Trend>('care_trend', { person: p, kind, drug, now }),
    appoint: (title: string, at: number, place: string, who: string, bring: string) => op<{ id: string }>('care_appoint', { person: p, title, at, place, who, bring }),
    appointments: (now = Date.now()) => op<Appointment[]>('care_appointments', { person: p, now }),
    editAppointment: (id: string, f: { title: string; at: number; place: string; who: string; bring: string }) => op<{ id: string }>('care_appointment_edit', { appointment_id: id, ...f }),
    editProfileItem: (id: string, text: string) => op<{ id: string; resolved_to: string }>('care_profile_edit', { item_id: id, text }),
    cancelAppointment: (id: string) => op<{ id: string }>('care_appointment_cancel', { appointment_id: id }),
    visit: (id = '', now = Date.now()) => op<Visit>('care_since_visit', { person: p, appointment_id: id, now }),
    profile: () => op<CareProfile>('care_profile', { person: p }),
    addCondition: (name: string) => op<{ id: string }>('care_condition_add', { person: p, name }),
    addAllergy: (text: string) => op<{ id: string; resolved_to: string }>('care_allergy_add', { person: p, text }),
    removeProfileItem: (id: string) => op<{ removed: string }>('care_profile_remove', { item_id: id }),
    allergyCheck: () => op<AllergyCheck>('care_allergy_check', { person: p }),
    people: () => op<People>('care_people'),
    divergence: (now: number) => op<Divergence>('care_divergence', { person: p, now }),
    reminders: (now: number) => op<Reminder[]>('care_reminders', { person: p, now }),
    ack: (dose_id: string) => op<{ id: string }>('care_ack', { dose_id }),
    record: (args: { edited?: string; product?: string; drug: string; action?: 'set' | 'stop'; dose_text: string; freq_text: string; source_type: string; quote: string; source_text: string; source_ref?: string }) =>
      op<{ id: string; status: string; warning?: string }>('care_record', { person: p, confirm: false, ...args }),
    confirm: (dose_id: string) => op<{ id: string }>('care_confirm', { dose_id }),
    give: (drug: string, slot: string) => op<GiveResult>('care_give', { person: p, drug, slot }),
    counts: () => op<Counts>('care_summary_counts', { person: p }),
    followupSuggest: (now: number) => op<FollowupSuggestion[]>('care_followup_suggest', { person: p, now }),
    followupAdd: (items: FollowupSuggestion[]) => op<{ added: string[]; skipped: number }>('care_followup_add', { person: p, items }),
    followups: () => op<Followup[]>('care_followups', { person: p }),
    followupDone: (id: string, dismiss = false) => op<{ id: string; status: string }>('care_followup_done', { followup_id: id, dismiss }),
    watched: () => op<string[]>('care_watched', { person: p }),
    watch: (drug: string, on: boolean) => op<{ drug: string; watched: boolean }>('care_watch', { person: p, drug, on }),
    witness: (drug: string, slot: string) => op<{ witnessed: boolean; by: string }>('care_witness', { person: p, drug, slot }),
    handovers: () => op<Handover[]>('care_handovers', { person: p }),
    handover: (text: string) => op<{ id: string }>('care_handover', { person: p, text }),
    gives: () => op<GiveRecord[]>('care_gives', { person: p }),
    hubs: () => op<Hubs>('care_hubs', { person: p }),
    influence: (metric: 'pagerank' | 'harmonic' | 'betweenness', top = 8) => op<GInfluence>('graph_influence', { metric, top }),
    communities: (method: 'wcc' | 'labelpropagation', top = 5) => op<GCommunities>('graph_communities', { method, top }),
    path: (source: string, target: string, sourceLabel: string, targetLabel: string) =>
      op<GPath>('graph_path', { source, target, source_label: sourceLabel, target_label: targetLabel }),
    graph: (now: number, include_history: boolean) => op<CareGraph>('care_graph', { person: p, include_history, now }),
    timeline: (now: number) => op<TimelineEvent[]>('care_timeline', { person: p, now, limit: 300 }),
    forget: (dose_id: string, reason: string) => op<{ receipt: string; forgotten: boolean; sha256: string }>('care_forget', { dose_id, reason }),
    forgetPerson: (confirm: string) => op<{ receipt: string; forgotten: boolean; removed_entries: number }>('care_forget_person', { person: p, confirm }),
    today: (now: number) => op<TodayView>('care_today', { person: p, now }),
    resolve: (text: string, n = 8) => op<Candidate[]>('care_drug_search', { text, n }),
    entrySource: (dose_id: string) => op<EntrySource>('care_entry_source', { dose_id }),
    outcomes: (now: number) => op<Outcomes>('care_outcomes', { person: p, days: 7, now }),
    consent: () => op<ConsentView>('care_consent', { person: p }),
    setConsent: (status: string, who: string, note: string) => op<{ id: string }>('care_consent_set', { person: p, status, who, note }),
    patientView: () => op<PatientView>('care_patient_view', { person: p }),
    reviews: () => op<Review[]>('care_pharmacist_reviews', { person: p }),
    stock: (now: number) => op<StockRow[]>('care_stock', { person: p, now }),
    setStock: (dose_id: string, doses_left: number) => op<{ id: string; doses_left: number }>('care_stock_set', { dose_id, doses_left }),
    timezone: () => op<{ tz: string; set: boolean }>('care_timezone'),
    setTimezone: (tz: string) => op<{ tz: string }>('care_set_timezone', { tz }),
    giveSlot: (dose_id: string, time: string) => op<GiveResult>('care_give_slot', { person: p, dose_id, time }),
    setSchedule: (dose_id: string, times: string[], as_needed: boolean, ends_on: string) => op<{ id: string }>('care_schedule_set', { dose_id, times, as_needed, ends_on }),
    markMistake: (dose_id: string, reason: string) => op<{ id: string }>('care_mark_mistake', { dose_id, reason }),
    restoreEntry: (dose_id: string) => op<{ id: string }>('care_restore_entry', { dose_id }),
    me: () => get<{ tenants: Record<string, string[]> }>('/v1/me', token),
    receipts: () => op<Receipt[]>('care_receipts'),
    fhir: (coded = false) => op<FhirBundle>('care_export_fhir', { person: p, coded }),
    chat: () => op<ChatMessage[]>('care_chat_history', { limit: 60 }),
    ask: (question: string, lang = '') => op<ChatMessage>('care_chat_ask', { person: p, question, lang }),
    clearChat: () => op<{ cleared: boolean }>('care_chat_clear'),
    members: () => get<Member[]>(`/v1/circles/${encodeURIComponent(s.circle)}/members`, token),
    intake: async (body: FormData): Promise<IntakeResult> => {
      const r = await fetch(`${base}/intake`, { method: 'POST', headers: { authorization: `Bearer ${token}` }, body });
      return parse<IntakeResult>(r);
    },
  };
}
export type Api = ReturnType<typeof apiFor>;

// ---------------------------------------------------------------- accounts (no circle needed)
export const authConfig = () => fetch('/v1/auth/config').then((r) => parse<AuthConfig>(r));
const jsonPost = <T>(path: string, body: unknown, token = '') =>
  fetch(path, { method: 'POST', headers: token ? bearer(token) : { 'content-type': 'application/json' }, body: JSON.stringify(body) }).then((r) => parse<T>(r));

export interface Signed {
  token: string;
  account: Account;
}
export const signUpLocal = (email: string, password: string, name: string) => jsonPost<Signed>('/v1/auth/signup', { email, password, name });
export const signInLocal = (email: string, password: string) => jsonPost<Signed>('/v1/auth/signin', { email, password });
export const exchangeCognito = (idToken: string, name: string) => jsonPost<Signed>('/v1/auth/exchange', { name }, idToken);
export const signOutRemote = (token: string) => jsonPost<{ ok: boolean }>('/v1/auth/signout', {}, token).catch(() => undefined);

export function accountApi(token: string) {
  return {
    profile: () => get<Profile>('/v1/account', token),
    rename: (name: string) => send<Profile>('PATCH', '/v1/account', token, { name }),
    changePassword: (old: string, next: string) => send<{ ok: boolean }>('POST', '/v1/account/password', token, { old, new: next }),
    deleteAccount: (confirm: string) => send<{ deleted: boolean; circles_deleted: number }>('DELETE', '/v1/account', token, { confirm }),
    createCircle: (name: string, person: string) => send<CircleInfo>('POST', '/v1/account/circles', token, { name, person }),
    join: (code: string) => send<CircleInfo>('POST', '/v1/join', token, { code }),
    renameCircle: (id: string, name: string) => send<{ ok: boolean }>('PATCH', `/v1/circles/${encodeURIComponent(id)}`, token, { name }),
    shareNew: (id: string, person: string, hours: number, note: string) => send<ShareLink>('POST', `/v1/circles/${encodeURIComponent(id)}/shares`, token, { person, hours, note }),
    shares: (id: string) => get<ShareRow[]>(`/v1/circles/${encodeURIComponent(id)}/shares`, token),
    shareRevoke: (id: string, share: string) => send<{ revoked: string }>('DELETE', `/v1/circles/${encodeURIComponent(id)}/shares/${encodeURIComponent(share)}`, token),
    invite: (id: string) => send<Invite>('POST', `/v1/circles/${encodeURIComponent(id)}/invites`, token),
    members: (id: string) => get<Member[]>(`/v1/circles/${encodeURIComponent(id)}/members`, token),
    leave: (id: string) => send<{ deleted_circle: boolean }>('POST', `/v1/circles/${encodeURIComponent(id)}/leave`, token),
    remove: (id: string, member: string) => send<{ deleted_circle: boolean }>('DELETE', `/v1/circles/${encodeURIComponent(id)}/members/${encodeURIComponent(member)}`, token),
    telegramCode: () => send<{ code: string; minutes: number }>('POST', '/v1/account/telegram-code', token),
    telegramUnlink: () => send<{ ok: boolean }>('DELETE', '/v1/account/telegram', token),
    resetDemo: () => send<{ ok: boolean }>('POST', '/v1/demo/reset', token),
    quiet: () => get<{ from: number | null; to: number | null; tz: number }>('/v1/account/quiet', token),
    setQuiet: (start: number | null, end: number | null, tz: number) => send<{ from: number | null; to: number | null; tz: number }>('PUT', '/v1/account/quiet', token, { start, end, tz }),
    signOutAll: () => send<{ signed_out: number }>('POST', '/v1/account/signout-all', token),
    exportAll: () => get<Record<string, unknown>>('/v1/account/export', token),
    deleteCircle: (id: string, confirm: string) => send<{ deleted_circle: boolean }>('DELETE', `/v1/circles/${encodeURIComponent(id)}`, token, { confirm }),
  };
}
export type AccountApi = ReturnType<typeof accountApi>;

// ---------------------------------------------------------------- the throw-away anonymous demo
export async function startDemo(): Promise<Session> {
  const r = await fetch('/demo/start', { method: 'POST' });
  if (!r.ok) {
    const said = ((await r.json().catch(() => ({}))) as { detail?: unknown }).detail;                 // 429 and 503 say why, in words a person can use
    throw new ApiError(typeof said === 'string' && said ? said : 'Could not start the demo', r.status);
  }
  const j = (await r.json()) as { circle: string; person: string; keys: Record<string, string> };
  return { circle: j.circle, person: j.person, keys: j.keys, as: Object.keys(j.keys)[0] ?? '', demoCircle: true };
}

export async function sampleLabel(): Promise<File> {
  const b = await (await fetch('/demo/label.png')).blob();
  return new File([b], 'label.png', { type: 'image/png' });
}

export async function healthy(): Promise<boolean> {
  try {
    return (await fetch('/healthz')).ok;
  } catch {
    return false;
  }
}
