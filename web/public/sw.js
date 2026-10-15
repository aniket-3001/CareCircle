/* Care Circle service worker: shows a reminder pushed by the server, and opens the app on the right tab when it is tapped. It caches nothing. */
self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = { body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(d.title || 'Care Circle', { body: d.body || '', tag: 'care-circle', data: { tab: d.tab || 'circle' } }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = '/#/' + ((event.notification.data && event.notification.data.tab) || 'circle');
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((all) => {
    for (const c of all) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
