const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'content-type': 'application/json; charset=utf-8' },
});

const publicFields = ['id', 'title', 'body', 'sourceUrl', 'organization', 'region', 'publishedAt', 'origin'];
const expose = article => Object.fromEntries(publicFields.map(key => [key, article[key] ?? '']));
const normalized = value => String(value ?? '').toLocaleLowerCase('ko-KR');

export async function handleNews(request, context) {
  const url = new URL(request.url);
  if (!/^\/api\/news(?:\/|$)/.test(url.pathname)) return null;
  if (request.method !== 'GET') return json({ ok: false, error: 'GET 요청만 지원합니다.' }, 405);
  const published = (context.read().articles || [])
    .filter(article => article.status === 'published')
    .sort((a, b) => String(b.publishedAt ?? '').localeCompare(String(a.publishedAt ?? '')));

  if (url.pathname === '/api/news/articles') {
    const query = normalized(url.searchParams.get('q')).trim();
    const region = normalized(url.searchParams.get('region')).trim();
    const items = published.filter(article =>
      (!query || ['title', 'body', 'organization'].some(key => normalized(article[key]).includes(query))) &&
      (!region || normalized(article.region).includes(region))
    ).map(expose);
    return json({ ok: true, items });
  }

  if (url.pathname === '/api/news/briefing') {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(new Date());
    const part = type => parts.find(value => value.type === type).value;
    const date = `${part('year')}-${part('month')}-${part('day')}`;
    return json({ ok: true, date, count: published.length, label: '규칙 요약', items: published.map(article => ({
      id: article.id, title: article.title, summary: String(article.body ?? '').slice(0, 180),
      sourceUrl: article.sourceUrl, publishedAt: article.publishedAt,
    })) });
  }

  const detail = url.pathname.match(/^\/api\/news\/articles\/([^/]+)$/);
  if (detail) {
    let id;
    try { id = decodeURIComponent(detail[1]); } catch { return json({ ok: false, error: '기사를 찾을 수 없습니다.' }, 404); }
    const article = published.find(item => item.id === id);
    return article ? json({ ok: true, item: expose(article) }) : json({ ok: false, error: '기사를 찾을 수 없습니다.' }, 404);
  }
  return json({ ok: false, error: '경로를 찾을 수 없습니다.' }, 404);
}
