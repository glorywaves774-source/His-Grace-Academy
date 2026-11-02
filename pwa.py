"""Installable-app (PWA) support for the school systems.

Serves /manifest.webmanifest, /sw.js and /offline. The service worker caches ONLY public static
files (CSS, JS, icons) and the offline page. Pages with student, fee or staff data are never cached,
so nothing private is left on a shared device after sign-out.
"""
import hashlib
import json
from pathlib import Path

from flask import Response, render_template_string

OFFLINE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="{{ theme }}">
<title>Offline | {{ name }}</title><link rel="stylesheet" href="/static/style.css"></head>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:{{ background }};font-family:system-ui,sans-serif">
<main style="max-width:420px;margin:24px;padding:32px 26px;background:#fff;border-radius:18px;text-align:center;box-shadow:0 12px 40px #0001">
<img src="/static/icons/icon-192.png" alt="" width="84" height="84" style="border-radius:20px">
<h1 style="font-size:22px;margin:18px 0 8px;color:{{ theme }}">You are offline</h1>
<p style="color:#4a4452;line-height:1.6;margin:0 0 20px">{{ name }} needs an internet connection to show records. For privacy, student and fee information is never stored on this device. Please reconnect and try again.</p>
<a href="/" style="display:inline-block;background:{{ theme }};color:#fff;padding:12px 22px;border-radius:10px;font-weight:700;text-decoration:none">Try again</a>
</main></body></html>"""

SERVICE_WORKER = """'use strict';
// Caches public static files only. Pages with school records are always fetched from the network.
const CACHE = 'school-static-__VERSION__';
const OFFLINE_URL = '/offline';
const PRECACHE = __PRECACHE__;

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      const cached = await cache.match(request);
      const network = fetch(request).then(response => {
        if (response.ok && response.type === 'basic') cache.put(request, response.clone());
        return response;
      }).catch(() => cached);
      return cached || network;
    }));
  }
});
"""


def _asset_version(static_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ('style.css', 'app.js'):
        path = static_dir / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def register_pwa(app, *, name, short_name, theme, background, description):
    static_dir = Path(app.static_folder)
    manifest = {
        'id': '/', 'name': name, 'short_name': short_name, 'description': description,
        'start_url': '/', 'scope': '/', 'display': 'standalone', 'orientation': 'any',
        'background_color': background, 'theme_color': theme, 'lang': 'en', 'categories': ['education'],
        'icons': [
            {'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    precache = ['/offline', '/static/style.css', '/static/app.js'] + [i['src'] for i in manifest['icons']]
    worker = SERVICE_WORKER.replace('__VERSION__', _asset_version(static_dir)).replace('__PRECACHE__', json.dumps(precache))
    manifest_json = json.dumps(manifest, indent=2)

    @app.route('/manifest.webmanifest', endpoint='pwa_manifest')
    def pwa_manifest():
        return Response(manifest_json, mimetype='application/manifest+json', headers={'Cache-Control': 'no-cache'})

    @app.route('/sw.js', endpoint='pwa_sw')
    def pwa_sw():
        return Response(worker, mimetype='application/javascript',
                        headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})

    @app.route('/offline', endpoint='pwa_offline')
    def pwa_offline():
        return render_template_string(OFFLINE_PAGE, name=name, theme=theme, background=background)

    return {'pwa_manifest', 'pwa_sw', 'pwa_offline'}
