import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import worker from '../modules/opportunity-radar/worker/index.js';
import { handleDesk } from '../modules/editorial-desk/server.mjs';
import { handleNews } from '../modules/regional-news/server.mjs';
import { createStore } from './store.mjs';
import { handleRelay } from './relay.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const port = Number(process.env.PORT || 3100);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid PORT');
const origin = `http://127.0.0.1:${port}`;
const allowedOrigins = new Set([origin, `http://localhost:${port}`]);
const context = createStore(process.env.ARCHIVEKR_DATA_FILE || resolve(root, '.local/data.json'));
context.read(); // Fail visibly on invalid existing data; never overwrite it.
const assets = new Map([
  ['/', ['web/index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['web/app.js', 'text/javascript; charset=utf-8']],
  ['/style.css', ['web/style.css', 'text/css; charset=utf-8']],
  ['/radar-bridge.js', ['web/radar-bridge.js', 'text/javascript; charset=utf-8']],
]);
function json(data, status = 200) { return Response.json(data, { status }); }

export async function route(request) {
  const url = new URL(request.url);
  const mutation = !['GET', 'HEAD'].includes(request.method);
  // This is a loopback-only internal development desk. Block cross-site writes.
  if (mutation && request.headers.get('origin') && !allowedOrigins.has(request.headers.get('origin'))) return json({ ok: false, error: '허용되지 않은 요청 출처입니다.' }, 403);
  if (request.headers.get('sec-fetch-site') === 'cross-site') return json({ ok: false, error: '교차 사이트 요청은 허용하지 않습니다.' }, 403);
  if (url.pathname === '/api/health') return json({ ok: true, name: 'archiveKR', modules: ['radar', 'desk', 'news', 'movist'], storage: 'local-file' });
  if (url.pathname === '/movist' || url.pathname.startsWith('/movist/') || url.pathname.startsWith('/api/movist/')) {
    try {
      const headers = new Headers(request.headers);
      headers.delete('host'); headers.delete('connection'); headers.delete('content-length');
      const response = await fetch(new URL(url.pathname + url.search, 'http://127.0.0.1:3102'), {
        method: request.method, headers,
        ...(mutation ? { body: await request.arrayBuffer() } : {}),
        signal: AbortSignal.timeout(120000), redirect: 'manual',
      });
      const outHeaders = new Headers(response.headers);
      outHeaders.delete('content-encoding'); outHeaders.delete('content-length');
      return new Response(await response.arrayBuffer(), { status: response.status, headers: outHeaders });
    } catch { return json({ ok: false, error: '영화 제작실 서버를 시작하세요. README의 실행 명령을 확인하세요.' }, 503); }
  }
  if (url.pathname.startsWith('/api/desk/')) return await handleDesk(request, context) || json({ ok: false, error: '경로가 없습니다.' }, 404);
  if (url.pathname.startsWith('/api/news/')) return await handleNews(request, context) || json({ ok: false, error: '경로가 없습니다.' }, 404);
  if (url.pathname.startsWith('/api/')) return await handleRelay(request, process.env) || worker.fetch(request, process.env);
  if (!['GET', 'HEAD'].includes(request.method)) return json({ ok: false, error: '허용되지 않은 메서드입니다.' }, 405);
  if (url.pathname === '/radar' || url.pathname === '/radar/') {
    const response = await worker.fetch(new Request(new URL('/', request.url)), process.env);
    const html = (await response.text()).replace('</body>', '<script src="/radar-bridge.js"></script></body>');
    return new Response(html, { status: response.status, headers: { 'content-type': 'text/html; charset=utf-8' } });
  }
  const asset = assets.get(url.pathname);
  if (!asset) return json({ ok: false, error: '경로가 없습니다.' }, 404);
  return new Response(readFileSync(resolve(root, asset[0])), { headers: { 'content-type': asset[1] } });
}

const server = createServer(async (req, res) => {
  try {
    if (req.headers.host !== `127.0.0.1:${port}` && req.headers.host !== `localhost:${port}`) {
      res.writeHead(403); res.end('Invalid host'); return;
    }
    let size = 0;
    const chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 1024 * 1024) { res.writeHead(413, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: false, error: '요청 본문이 너무 큽니다.' })); return; }
      chunks.push(chunk);
    }
    const headers = new Headers();
    for (const [key, value] of Object.entries(req.headers)) if (value !== undefined) headers.set(key, Array.isArray(value) ? value.join(', ') : value);
    const method = req.method || 'GET';
    const request = new Request(new URL(req.url || '/', origin), { method, headers, ...(!['GET', 'HEAD'].includes(method) && chunks.length ? { body: Buffer.concat(chunks) } : {}) });
    const response = await route(request);
    res.statusCode = response.status;
    response.headers.forEach((value, key) => res.setHeader(key, value));
    res.setHeader('x-content-type-options', 'nosniff');
    res.setHeader('referrer-policy', 'no-referrer');
    res.setHeader('cache-control', 'no-store');
    res.setHeader('x-frame-options', 'SAMEORIGIN');
    if (method === 'HEAD') res.end(); else res.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    if (!res.headersSent) { res.writeHead(500, { 'content-type': 'application/json' }); res.end(JSON.stringify({ ok: false, error: '요청 처리 실패. 서버 상태와 데이터 파일을 확인하세요.' })); }
    else res.end();
  }
});
server.on('error', () => { console.error('archiveKR startup failed: check port and file permissions.'); process.exitCode = 1; });
server.listen(port, '127.0.0.1', () => console.log(`archiveKR listening on port ${port}`));
process.on('SIGTERM', () => server.close());
process.on('SIGINT', () => server.close());
