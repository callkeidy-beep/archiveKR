import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { handleDesk } from '../modules/editorial-desk/server.mjs';
import { createStore } from './store.mjs';
import { createAutomation } from '../modules/automation/server.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const port = Number(process.env.PORT || 3100);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid PORT');
const origin = `http://127.0.0.1:${port}`;
const allowedOrigins = new Set([origin, `http://localhost:${port}`]);
const moviePort = Number(process.env.ARCHIVEKR_MOVIST_PORT || 3102);
if (!Number.isInteger(moviePort) || moviePort < 1 || moviePort > 65535) throw new Error('Invalid movie service port');
const movieOrigin = `http://127.0.0.1:${moviePort}`;
const dataFile = process.env.ARCHIVEKR_DATA_FILE || resolve(root, '.local/data.json');
const context = createStore(dataFile);
context.read(); // Fail visibly on invalid existing data; never overwrite it.
async function movieJson(path, options = {}) {
  const signal = options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(60000)]) : AbortSignal.timeout(60000);
  const r = await fetch(movieOrigin + '/api/movist/' + path, { ...options, signal });
  const data = await r.json();
  if (!r.ok) throw new Error('MOVIST 수집 서버에서 기사 본문을 확인하지 못했습니다. 연결 상태를 확인하세요.');
  return data;
}
const automation = createAutomation(context, {
  artifactDir: resolve(dirname(dataFile), 'automation'),
  fetchArticle: (url, options) => movieJson('fetch?url=' + encodeURIComponent(url), options),
  discoverArticles: async (_sourceUrl, options) => (await movieJson('latest', options)).items.map(item => item.url),
  renderCard: async (data, { signal } = {}) => {
    const r = await fetch(movieOrigin + '/api/movist/cards', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(data), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000) });
    if (!r.ok) throw new Error('영화 제작실에서 카드 이미지를 만들지 못했습니다.');
    return r.arrayBuffer();
  },
});
const backgroundEnabled = process.env.ARCHIVEKR_AUTOMATION_BACKGROUND !== '0';
function runAutomation() { if (backgroundEnabled) automation.tick().catch(() => console.error('Automation worker failed; inspect job status.')); }
const automationTimer = backgroundEnabled ? setInterval(runAutomation, 5000) : null;
automationTimer?.unref();
if (backgroundEnabled) { const initial = setTimeout(runAutomation, 1500); initial.unref(); }
const assets = new Map([
  ['/', ['web/index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['web/app.js', 'text/javascript; charset=utf-8']],
  ['/style.css', ['web/style.css', 'text/css; charset=utf-8']],
  ['/radar-bridge.js', ['web/radar-bridge.js', 'text/javascript; charset=utf-8']],
  ['/studio-bridge.js', ['web/studio-bridge.js', 'text/javascript; charset=utf-8']],
]);
function json(data, status = 200) { return Response.json(data, { status }); }

export async function route(request) {
  const url = new URL(request.url);
  const mutation = !['GET', 'HEAD'].includes(request.method);
  // This is a loopback-only internal development desk. Block cross-site writes.
  if (mutation && request.headers.get('origin') && !allowedOrigins.has(request.headers.get('origin'))) return json({ ok: false, error: '허용되지 않은 요청 출처입니다.' }, 403);
  if (request.headers.get('sec-fetch-site') === 'cross-site') return json({ ok: false, error: '교차 사이트 요청은 허용하지 않습니다.' }, 403);
  if (url.pathname === '/api/health') return json({ ok: true, name: 'archiveKR', modules: ['desk', 'movist', 'automation'], suspendedModules: ['radar', 'news'], storage: 'local-file' });
  if (url.pathname === '/api/automation' || url.pathname.startsWith('/api/automation/')) {
    const response = await automation.handle(request);
    if (mutation && response.ok) runAutomation();
    return response;
  }
  if (url.pathname === '/movist' || url.pathname.startsWith('/movist/') || url.pathname.startsWith('/api/movist/')) {
    try {
      const headers = new Headers(request.headers);
      headers.delete('host'); headers.delete('connection'); headers.delete('content-length');
      const response = await fetch(new URL(url.pathname + url.search, movieOrigin), {
        method: request.method, headers,
        ...(mutation ? { body: await request.arrayBuffer() } : {}),
        signal: AbortSignal.timeout(120000), redirect: 'manual',
      });
      const outHeaders = new Headers(response.headers);
      outHeaders.delete('content-encoding'); outHeaders.delete('content-length');
      let body = await response.arrayBuffer();
      if (response.ok && url.pathname === '/api/movist/fetch') {
        const data = JSON.parse(Buffer.from(body).toString('utf8'));
        const job = automation.ingestFetched(url.searchParams.get('url'), data);
        data.archiveKR = { articleId: job.articleId, jobId: job.id };
        body = JSON.stringify(data);
        runAutomation();
      }
      if (response.ok && ['/movist','/movist/'].includes(url.pathname)) body = Buffer.from(body).toString('utf8').replace('</body>', '<script src="/studio-bridge.js"></script></body>');
      return new Response(body, { status: response.status, headers: outHeaders });
    } catch { return json({ ok: false, error: '영화 제작실 서버를 시작하세요. README의 실행 명령을 확인하세요.' }, 503); }
  }
  if (url.pathname.startsWith('/api/desk/')) {
    const response = await handleDesk(request, context);
    if (response?.ok && mutation) {
      const data = await response.clone().json();
      if (data.item && !url.pathname.endsWith('/transition')) { automation.enqueueArticle(data.item.id); runAutomation(); }
    }
    return response || json({ ok: false, error: '경로가 없습니다.' }, 404);
  }
  if (url.pathname.startsWith('/api/news/') || url.pathname.startsWith('/api/')) return json({ ok: false, suspended: true, error: '기회탐색·지역뉴스는 보존된 상태로 잠시 분리되었습니다.' }, 410);
  if (!['GET', 'HEAD'].includes(request.method)) return json({ ok: false, error: '허용되지 않은 메서드입니다.' }, 405);
  if (url.pathname === '/radar' || url.pathname === '/radar/') {
    return json({ ok: false, suspended: true, error: '기회탐색은 삭제하지 않고 잠시 분리했습니다.' }, 410);
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
function shutdown() { if (automationTimer) clearInterval(automationTimer); automation.stop?.(); server.close(); }
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
