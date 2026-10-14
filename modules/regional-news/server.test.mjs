import test from 'node:test';
import assert from 'node:assert/strict';
import { handleNews } from './server.mjs';

function fixture() {
  const state = { articles: [
    { id: 'draft', status: 'draft', title: '비공개 초안', body: '비밀' },
    { id: 'review', status: 'review', title: '비공개 검토', body: '비밀' },
    { id: 'old', status: 'published', title: '서울 문화', body: '전시 개최', organization: '문화재단', region: '서울', publishedAt: '2026-10-10T02:00:00.000Z', sourceUrl: 'https://example.org/old', origin: 'manual', questions: ['비공개 질문'], reviewedAt: 'secret', updatedAt: 'secret' },
    { id: 'new', status: 'published', title: '부산 공지', body: '가'.repeat(200), organization: '부산문화원', region: '부산', publishedAt: '2026-10-12T02:00:00.000Z', sourceUrl: 'https://example.org/new', origin: 'opportunity', questions: ['비공개 질문'] },
  ] };
  const context = { read: () => state };
  const request = (path, method = 'GET') => handleNews(new Request(`http://localhost${path}`, { method }), context);
  return { state, request };
}

test('public feed contains published articles only, newest first, with explicit safe fields', async () => {
  const { request } = fixture();
  const value = await (await request('/api/news/articles')).json();
  assert.deepEqual(value.items.map(item => item.id), ['new', 'old']);
  for (const item of value.items) {
    assert.deepEqual(Object.keys(item).sort(), ['id', 'title', 'body', 'sourceUrl', 'organization', 'region', 'publishedAt', 'origin'].sort());
  }
  for (const id of ['draft', 'review', 'missing']) assert.equal((await request(`/api/news/articles/${id}`)).status, 404);
  const detail = await (await request('/api/news/articles/old')).json();
  assert.equal(detail.item.questions, undefined);
  assert.equal(detail.item.reviewedAt, undefined);
});

test('search matches title, body and organization; region combines with search', async () => {
  const { request } = fixture();
  for (const query of ['서울', '전시', '문화재단']) {
    assert.deepEqual((await (await request(`/api/news/articles?q=${encodeURIComponent(query)}`)).json()).items.map(item => item.id), ['old']);
  }
  assert.deepEqual((await (await request('/api/news/articles?region=부')).json()).items.map(item => item.id), ['new']);
  assert.equal((await (await request('/api/news/articles?q=서울&region=부산')).json()).items.length, 0);
});

test('unpublished article disappears immediately from list, detail and briefing', async () => {
  const { request, state } = fixture();
  state.articles.find(item => item.id === 'new').status = 'draft';
  assert.deepEqual((await (await request('/api/news/articles')).json()).items.map(item => item.id), ['old']);
  assert.equal((await request('/api/news/articles/new')).status, 404);
  const briefing = await (await request('/api/news/briefing')).json();
  assert.equal(briefing.count, 1);
  assert.deepEqual(briefing.items.map(item => item.id), ['old']);
});

test('briefing uses Korean current date and literal first 180 characters, with no private metadata', async () => {
  const { request } = fixture();
  const before = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  const result = await (await request('/api/news/briefing')).json();
  const after = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  assert.ok([before, after].includes(result.date));
  assert.equal(result.label, '규칙 요약');
  assert.equal(result.count, 2);
  assert.equal(result.items[0].summary, '가'.repeat(180));
  assert.equal(result.items[1].summary, '전시 개최');
  assert.equal(result.items[0].sourceUrl, 'https://example.org/new');
  assert.equal(result.items[0].publishedAt, '2026-10-12T02:00:00.000Z');
  assert.equal(JSON.stringify(result).includes('비공개'), false);
});

test('news routes allow GET only; unrelated paths pass through', async () => {
  const { request } = fixture();
  assert.equal(await request('/api/desk/articles'), null);
  for (const method of ['POST', 'PATCH', 'DELETE']) assert.equal((await request('/api/news/articles', method)).status, 405);
  assert.equal((await request('/api/news/unknown')).status, 404);
});
