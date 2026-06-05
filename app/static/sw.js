/* Service Worker — modo offline e cache de shell.
 *
 * Estrategia:
 *   - install: pre-cache do shell (assets criticos + offline.html).
 *   - activate: limpa caches antigas (deploys anteriores).
 *   - fetch:
 *       /api/* e /auth/*  -> sempre rede (dados live, nada de cache).
 *       /health/*         -> idem.
 *       navegacao (HTML)  -> network first com timeout, fallback cache,
 *                            fallback offline.html.
 *       /static/*         -> cache first, fallback network (assets sao
 *                            versionados via ?v=hash, entao seguro).
 *
 * VERSION e substituida no servidor antes de servir esse arquivo. Quando
 * muda, o browser detecta um SW novo e re-instala — limpa cache antiga
 * via activate.
 */

const VERSION = '__SW_VERSION__';
const CACHE_NAME = `economart-${VERSION}`;
const OFFLINE_URL = '/offline.html';

// Assets pre-cacheados na instalacao do SW. Pra cobrir o caso de
// usuario abrir o app pela primeira vez offline (depois de instalar
// como PWA, por exemplo) — o shell ja esta la.
const PRECACHE = [
  OFFLINE_URL,
  '/static/img/logo.png',
  '/static/img/favicon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Force cache:reload pra ignorar cache do browser e baixar fresco.
      const requests = PRECACHE.map((url) => new Request(url, { cache: 'reload' }));
      return cache.addAll(requests).catch((err) => {
        // Se algum recurso falhar, nao quebra o install — SW ainda
        // funciona, apenas com cache parcial.
        console.warn('[sw] precache parcial:', err);
      });
    })
  );
  // Ativa imediatamente sem esperar tabs fecharem. Combinado com
  // clients.claim no activate, faz update do SW pegar na hora.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names
          .filter((n) => n.startsWith('economart-') && n !== CACHE_NAME)
          .map((n) => caches.delete(n))
      );
    }).then(() => self.clients.claim())
  );
});

function isApiPath(url) {
  return (
    url.pathname.startsWith('/api/')
    || url.pathname.startsWith('/auth/')
    || url.pathname.startsWith('/health')
    || url.pathname === '/sw.js'
  );
}

function isStaticAsset(url) {
  return url.pathname.startsWith('/static/');
}

async function networkFirstWithTimeout(request, timeoutMs) {
  // Race entre fetch e timeout. Se timeout vencer, tenta o cache.
  return new Promise((resolve, reject) => {
    let settled = false;
    const t = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error('network-timeout'));
      }
    }, timeoutMs);

    fetch(request)
      .then((resp) => {
        if (settled) return;
        settled = true;
        clearTimeout(t);
        // Salva copia no cache pra proximo carregamento offline.
        if (resp && resp.ok && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone)).catch(() => {});
        }
        resolve(resp);
      })
      .catch((err) => {
        if (settled) return;
        settled = true;
        clearTimeout(t);
        reject(err);
      });
  });
}

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // SW so intercepta GET. POST/PUT/DELETE passam direto.
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Skip cross-origin (CDN de fonts, opencnpj, etc.)
  if (url.origin !== self.location.origin) return;

  // Skip API/auth/health — sempre rede.
  if (isApiPath(url)) return;

  // Navegacao HTML: network first, fallback cache, fallback offline.
  const isNavigate = (
    req.mode === 'navigate'
    || (req.destination === '' && req.headers.get('Accept') && req.headers.get('Accept').includes('text/html'))
  );
  if (isNavigate) {
    event.respondWith((async () => {
      try {
        const resp = await networkFirstWithTimeout(req, 4000);
        return resp;
      } catch (_) {
        const cached = await caches.match(req);
        if (cached) return cached;
        const offline = await caches.match(OFFLINE_URL);
        if (offline) return offline;
        // Ultimo recurso — resposta minima inline.
        return new Response(
          '<h1>Sem conexao</h1><p>Sua conexao caiu. Tente novamente.</p>',
          { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      }
    })());
    return;
  }

  // Estaticos: cache first, fallback network.
  if (isStaticAsset(url)) {
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const resp = await fetch(req);
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone)).catch(() => {});
        }
        return resp;
      } catch (err) {
        // Asset que nunca foi cacheado e nao conseguimos baixar — 504.
        return new Response('', { status: 504 });
      }
    })());
    return;
  }

  // Outro caso: deixa passar (network normal).
});

// Mensagem do client pra forcar atualizacao manual do SW (futuro: botao
// 'verificar atualizacoes' nas configuracoes do usuario).
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
