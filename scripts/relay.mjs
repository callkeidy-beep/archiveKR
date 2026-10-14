// Reuse verified public collection endpoints; never send client keys or cookies.
const endpoint = 'https://opportunity-radar-vert-pi.vercel.app';
const routes = new Map([
  ['/api/kstartup', 'DATA_GO_KR_SERVICE_KEY'],
  ['/api/msit', 'DATA_GO_KR_SERVICE_KEY'],
  ['/api/g2b', 'G2B_SERVICE_KEY'],
  ['/api/bizinfo/support', 'BIZINFO_SUPPORT_KEY'],
  ['/api/bizinfo/events', 'BIZINFO_EVENT_KEY'],
  ['/api/mcst-rss', null],
  ['/api/mcst-press-rss', null],
]);
export async function handleRelay(request, env, fetcher = fetch) {
  const path = new URL(request.url).pathname;
  if (request.method !== 'GET' || !routes.has(path) || env.ARCHIVEKR_USE_RELAY === '0') return null;
  const key = routes.get(path);
  if (key && env[key]) return null;
  try {
    const upstream = await fetcher(endpoint + path, { headers: { accept: 'application/json' }, signal: AbortSignal.timeout(20000), redirect: 'error' });
    if (!upstream.ok) return Response.json({ ok: false, error: '기존 기회레이더 수집 서버 요청에 실패했습니다.', items: [] }, { status: 502 });
    const data = await upstream.json();
    if (data.ok !== true || !Array.isArray(data.items) || data.count !== data.items.length) throw new Error('Unexpected collection response');
    return Response.json({ ...data, relay: { name: '기존 기회레이더 수집 서버', url: endpoint, checkedAt: new Date().toISOString() } }, { headers: { 'x-archivekr-source': 'existing-opportunity-radar' } });
  } catch {
    return Response.json({ ok: false, error: '기존 수집 서버의 연결 또는 응답을 확인하지 못했습니다. 잠시 후 다시 수집하세요.', items: [] }, { status: 502 });
  }
}
