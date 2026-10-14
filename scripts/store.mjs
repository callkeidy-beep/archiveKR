import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

export function createStore(path) {
  const file = resolve(path);
  const empty = () => ({ version: 1, articles: [] });
  function read() {
    const state = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : empty();
    if (state.version !== 1 || !Array.isArray(state.articles)) throw new Error('Invalid archiveKR data file');
    return state;
  }
  return {
    read,
    update(mutator) {
      const state = read();
      const result = mutator(state);
      mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
      const temp = `${file}.tmp`;
      writeFileSync(temp, JSON.stringify(state, null, 2), { mode: 0o600 });
      renameSync(temp, file);
      return result;
    },
  };
}
