self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {
    data = { title: 'Pips Master Academy', body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'Pips Master Academy';
  const options = {
    body: data.body || '',
    icon: '/assets/images/profile-placeholder.svg',
    badge: '/assets/images/profile-placeholder.svg',
    tag: data.type ? 'pma-' + data.type : 'pma-notification',
    renotify: true,
    data: { target_page: data.target_page || 'home' }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const page = event.notification.data?.target_page || 'home';
  const url = new URL('/', self.location.origin);
  url.searchParams.set('pma_page', page);
  event.waitUntil(clients.matchAll({type:'window', includeUncontrolled:true}).then(list => {
    for (const client of list) {
      if ('focus' in client) return client.focus();
    }
    return clients.openWindow(url.href);
  }));
});
