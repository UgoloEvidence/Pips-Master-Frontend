self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {title:'Pips Master Academy', body:event.data?.text()||''}; }
  const title = data.title || 'Pips Master Academy';
  const options = {
    body: data.body || '',
    icon: '/assets/images/profile-placeholder.svg',
    badge: '/assets/images/profile-placeholder.svg',
    tag: 'pma-notification-' + (data.type || 'info'),
    data: {target_page: data.target_page || 'home'}
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = event.notification.data?.target_page || 'home';
  const url = new URL('/?open=' + encodeURIComponent(target), self.location.origin).href;
  event.waitUntil(clients.matchAll({type:'window', includeUncontrolled:true}).then(list => {
    for (const client of list) {
      if ('focus' in client) { client.focus(); client.postMessage({type:'pma-open-page', page:target}); return; }
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
