// Service worker do Assistente Financeiro: mostra as notificações (avisos de compra, venda e contas)
// e abre o app na aba certa quando a pessoa toca nelas. Não guarda dados em cache.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = {texto: e.data ? e.data.text() : ''}; }
  e.waitUntil(self.registration.showNotification(d.titulo || 'Assistente Financeiro', {
    body: d.texto || '', icon: '/icone-192.png', badge: '/icone-192.png', lang: 'pt-BR',
    tag: d.tag || undefined, data: {aba: d.aba || 'resumo'},
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = '/?aba=' + encodeURIComponent((e.notification.data || {}).aba || 'resumo');
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(ws => {
    for (const w of ws) {
      if (new URL(w.url).origin === self.location.origin) { w.postMessage({aba: (e.notification.data || {}).aba}); return w.focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
