import type {
  CareGraph, CheckResult, Divergence, FhirBundle, GiveRecord, GiveResult, Hubs, IntakeResult, Nudge, People, Receipt, RegimenEntry, Session,
  TimelineEvent,
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

/** The API for one signed-in carer: every call carries that carer's key, so the server checks their grants on each query. */
export function apiFor(s: Session) {
  const headers = { 'content-type': 'application/json', authorization: `Bearer ${s.keys[s.as] ?? ''}` };
  const op = <T>(name: string, args: Record<string, unknown> = {}) =>
    fetch(`/v1/tenants/${encodeURIComponent(s.circle)}/${name}`, { method: 'POST', headers, body: JSON.stringify(args) }).then((r) => parse<T>(r));
  const p = s.person;
  return {
    check: (as_of?: number) => op<CheckResult>('care_check', { person: p, ...(as_of === undefined ? {} : { as_of }) }),
    regimen: (as_of?: number) => op<RegimenEntry[]>('care_regimen', { person: p, ...(as_of === undefined ? {} : { as_of }) }),
    people: () => op<People>('care_people'),
    divergence: (now: number) => op<Divergence>('care_divergence', { person: p, now }),
    nudges: (now: number) => op<Nudge[]>('care_nudges', { person: p, now }),
    ack: (dose_id: string) => op<{ id: string }>('care_ack', { dose_id }),
    record: (args: { drug: string; person?: string; dose_text: string; freq_text: string; source_type: string; quote: string; source_text: string }) =>
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
    intake: async (body: FormData): Promise<IntakeResult> => {
      const r = await fetch(`/v1/tenants/${encodeURIComponent(s.circle)}/intake`, {
        method: 'POST', headers: { authorization: headers.authorization }, body,
      });
      return parse<IntakeResult>(r);
    },
  };
}
export type Api = ReturnType<typeof apiFor>;

export async function startDemo(): Promise<Session> {
  const r = await fetch('/demo/start', { method: 'POST' });
  if (!r.ok) throw new ApiError('Could not start the demo', r.status);
  const j = (await r.json()) as { circle: string; person: string; keys: Record<string, string> };
  return { circle: j.circle, person: j.person, keys: j.keys, as: Object.keys(j.keys)[0] ?? '' };
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
