/* Care Circle service worker: shows a reminder pushed by the server (a newer one replaces an older one still on screen, and alerts again), and opens the app on the right tab when it is tapped. It caches nothing. */
// A new version takes over at once (it caches nothing, so there is nothing to migrate).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = { body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(d.title || 'Care Circle', { body: d.body || '', tag: 'care-circle', renotify: true, data: { tab: d.tab || 'circle' } }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = '/#/' + ((event.notification.data && event.notification.data.tab) || 'circle');
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((all) => {
    for (const c of all) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
