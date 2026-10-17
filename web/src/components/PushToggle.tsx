import { Bell, BellOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { authHeaders } from '../api/client';
import { tr } from '../lib/i18n';
import { useApp } from '../state';
import { useToast } from './Toast';

const b64 = (s: string): Uint8Array => {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};
const supported = (): boolean => typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

/** Reminders as browser notifications, with no chat app needed. Off unless the server has keys and the person allows it in the browser. */
export function PushToggle(): React.JSX.Element | null {
  const app = useApp();
  const toast = useToast();
  const token = app.session.keys[app.session.as] ?? app.session.keys.me ?? '';
  const [key, setKey] = useState('');
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supported()) return;
    fetch('/v1/push/config').then((r) => r.json()).then((c: { enabled: boolean; key: string }) => { if (c.enabled) setKey(c.key); }).catch(() => undefined);
    navigator.serviceWorker.getRegistration('/sw.js').then((r) => r?.pushManager.getSubscription()).then((s) => setOn(!!s)).catch(() => undefined);
  }, []);
  if (!supported() || !key) return null;

  async function enable(): Promise<void> {
    setBusy(true);
    try {
      if ((await Notification.requestPermission()) !== 'granted') { toast(tr('Notifications are blocked in this browser. Allow them in the site settings.')); return; }
      const reg = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) as BufferSource });
      const j = sub.toJSON();
      const r = await fetch('/v1/push/subscribe', { method: 'POST', headers: authHeaders(token, { 'content-type': 'application/json' }), body: JSON.stringify({ endpoint: j.endpoint, p256dh: j.keys?.p256dh, auth: j.keys?.auth }) });
      if (!r.ok) throw new Error('The server did not accept the subscription.');
      const t = await fetch('/v1/push/test', { method: 'POST', headers: authHeaders(token) });
      const sent = t.ok ? ((await t.json()) as { sent?: number }).sent ?? 0 : 0;
      setOn(true);
      toast(sent > 0 ? tr('Notifications are on for this browser.') : tr('Notifications are on, but the test message did not arrive. Reminders may not reach this browser.'));
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not switch notifications on');
    } finally { setBusy(false); }
  }
  async function disable(): Promise<void> {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.getRegistration('/sw.js');
      await (await reg?.pushManager.getSubscription())?.unsubscribe();
      await fetch('/v1/push/subscribe', { method: 'DELETE', headers: authHeaders(token) });
      setOn(false);
      toast(tr('Notifications are off for this browser.'));
    } finally { setBusy(false); }
  }

  return (
    <section className="card" aria-labelledby="push-title" data-testid="push">
      <div className="row"><Bell size={20} aria-hidden="true" /><h2 id="push-title">{tr('Notifications')}</h2></div>
      <p className="muted">{tr('Get a reminder on this phone or computer when a change has not been seen, without any chat app.')}</p>
      <button type="button" className="btn btn--soft" disabled={busy} onClick={() => void (on ? disable() : enable())}>
        {on ? <BellOff size={18} aria-hidden="true" /> : <Bell size={18} aria-hidden="true" />} {tr(on ? 'Turn notifications off' : 'Turn notifications on')}
      </button>
    </section>
  );
}
