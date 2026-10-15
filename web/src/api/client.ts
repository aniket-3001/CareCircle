import type { DrugInfo,
  Account, AuthConfig, CareGraph, ChatMessage, CheckResult, Divergence, FhirBundle, GiveRecord, GiveResult, Hubs, IntakeResult, Invite, Member, Reminder, People,
  Profile, Receipt, RegimenEntry, Session, TimelineEvent, CircleInfo,
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
const get = <T>(path: string, token: string) => fetch(path, { headers: bearer(token) }).then((r) => parse<T>(r));
const send = <T>(method: string, path: string, token: string, body?: unknown) =>
  fetch(path, { method, headers: bearer(token), body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => parse<T>(r));

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
    people: () => op<People>('care_people'),
    divergence: (now: number) => op<Divergence>('care_divergence', { person: p, now }),
    reminders: (now: number) => op<Reminder[]>('care_reminders', { person: p, now }),
    ack: (dose_id: string) => op<{ id: string }>('care_ack', { dose_id }),
    record: (args: { drug: string; action?: 'set' | 'stop'; dose_text: string; freq_text: string; source_type: string; quote: string; source_text: string }) =>
      op<{ id: string; status: string }>('care_record', { person: p, confirm: false, ...args }),
    confirm: (dose_id: string) => op<{ id: string }>('care_confirm', { dose_id }),
    give: (drug: string, slot: string) => op<GiveResult>('care_give', { person: p, drug, slot }),
    gives: () => op<GiveRecord[]>('care_gives', { person: p }),
    hubs: () => op<Hubs>('care_hubs', { person: p }),
    graph: (now: number, include_history: boolean) => op<CareGraph>('care_graph', { person: p, include_history, now }),
    timeline: (now: number) => op<TimelineEvent[]>('care_timeline', { person: p, now, limit: 60 }),
    forget: (dose_id: string, reason: string) => op<{ receipt: string; forgotten: boolean; sha256: string }>('care_forget', { dose_id, reason }),
    forgetPerson: (confirm: string) => op<{ receipt: string; forgotten: boolean; removed_entries: number }>('care_forget_person', { person: p, confirm }),
    receipts: () => op<Receipt[]>('care_receipts'),
    fhir: () => op<FhirBundle>('care_export_fhir', { person: p }),
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
    invite: (id: string) => send<Invite>('POST', `/v1/circles/${encodeURIComponent(id)}/invites`, token),
    members: (id: string) => get<Member[]>(`/v1/circles/${encodeURIComponent(id)}/members`, token),
    leave: (id: string) => send<{ deleted_circle: boolean }>('POST', `/v1/circles/${encodeURIComponent(id)}/leave`, token),
    remove: (id: string, member: string) => send<{ deleted_circle: boolean }>('DELETE', `/v1/circles/${encodeURIComponent(id)}/members/${encodeURIComponent(member)}`, token),
    telegramCode: () => send<{ code: string; minutes: number }>('POST', '/v1/account/telegram-code', token),
    telegramUnlink: () => send<{ ok: boolean }>('DELETE', '/v1/account/telegram', token),
    resetDemo: () => send<{ ok: boolean }>('POST', '/v1/demo/reset', token),
  };
}
export type AccountApi = ReturnType<typeof accountApi>;

// ---------------------------------------------------------------- the throw-away anonymous demo
export async function startDemo(): Promise<Session> {
  const r = await fetch('/demo/start', { method: 'POST' });
  if (!r.ok) throw new ApiError('Could not start the demo', r.status);
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
