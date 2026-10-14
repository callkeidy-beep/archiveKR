import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createStore } from '../scripts/store.mjs';

test('file store survives reopening and does not save a failed mutation', () => {
  const dir = mkdtempSync(join(tmpdir(), 'archivekr-store-'));
  try {
    const file = join(dir, 'state.json');
    const store = createStore(file);
    store.update(s => s.articles.push({ id: 'persisted' }));
    assert.equal(createStore(file).read().articles[0].id, 'persisted');
    assert.throws(() => store.update(s => { s.articles = []; throw new Error('abort'); }));
    assert.equal(store.read().articles.length, 1);
    writeFileSync(file, '{broken');
    assert.throws(() => store.read());
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
