import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const python = resolve(root, 'modules/movist/.venv/bin/python');
if (!existsSync(python)) throw new Error('Run npm run setup first');
const children = [
  spawn(python, ['-u', 'modules/movist/app_server.py'], { cwd: root, stdio: 'inherit' }),
  spawn(process.execPath, ['--use-env-proxy', 'scripts/server.mjs'], { cwd: root, stdio: 'inherit', env: { ...process.env, NO_PROXY: [process.env.NO_PROXY || '', '127.0.0.1', 'localhost'].filter(Boolean).join(',') } }),
];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true; process.exitCode = code;
  for (const child of children) if (child.exitCode === null) child.kill('SIGTERM');
}
for (const child of children) {
  child.on('error', () => { console.error('archiveKR service failed to start.'); stop(1); });
  child.on('exit', code => { if (!stopping) stop(code || 1); });
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
