const CACHE_NAME = 'taxmanager-v5';
const STATIC_URLS = [
  'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_URLS).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = req.url;

  // Firebase / Google Auth는 캐시 건너뜀
  if (url.includes('firebase') || url.includes('google') || url.includes('gstatic')) return;

  // HTML 문서(페이지 내비게이션) → 항상 '네트워크 우선' → 배포 즉시 반영, 오프라인이면 캐시 폴백
  //  경로에 상관없이 navigate/document/text/html 요청이면 최신 index.html을 받아온다.
  const isHTML = req.mode === 'navigate'
    || req.destination === 'document'
    || ((req.headers.get('accept') || '').includes('text/html'));
  if (isHTML) {
    event.respondWith(
      fetch(req).then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
        }
        return resp;
      }).catch(() => caches.match(req).then(m => m || caches.match('index.html')))
    );
    return;
  }

  // 정적 자산(XLSX 등) → 캐시 우선
  event.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req).then(resp => {
        if (resp && resp.status === 200 && req.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
        }
        return resp;
      }).catch(() => cached);
    })
  );
});
