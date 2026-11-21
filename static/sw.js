// Service worker do Assistente Financeiro: mostra as notificações (avisos de compra, venda e contas), abre o app na
// aba certa quando a pessoa toca nelas e mostra uma página amigável quando não há internet.
// Não guarda dados da carteira em cache: eles ficam no aparelho (localStorage) e no servidor.
const CACHE = 'af-v2';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/offline.html', '/icone-192.png'])).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));

self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;  // só a abertura de páginas: o resto segue direto para a rede
  e.respondWith(fetch(e.request).catch(() => caches.match('/offline.html')));
});

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = {texto: e.data ? e.data.text() : ''}; }
  e.waitUntil(self.registration.showNotification(d.titulo || 'Assistente Financeiro', {
    body: d.texto || '', icon: '/icone-192.png', badge: '/icone-monocromatico.png', lang: 'pt-BR',
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
