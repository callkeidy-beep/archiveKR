import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Script } from 'node:vm';
import worker from '../modules/opportunity-radar/worker/index.js';

test('radar build preserves dollar syntax and serves the exact source HTML', async () => {
  const response = await worker.fetch(new Request('http://localhost/'), {});
  const html = await response.text();
  assert.equal(response.status, 200);
  assert.equal(html, readFileSync(new URL('../modules/opportunity-radar/app/index.html', import.meta.url), 'utf8'));
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  assert.doesNotThrow(() => new Script(script));
});
