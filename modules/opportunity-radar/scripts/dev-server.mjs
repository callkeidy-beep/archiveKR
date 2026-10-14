import { createServer } from 'node:http';
import worker from '../worker/index.js';

const host = '127.0.0.1';
const port = Number(process.env.PORT || 3101);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('PORT must be an integer between 1 and 65535');
}
const maxBody = 1024 * 1024;
const server = createServer(async (req, res) => {
  try {
    let size = 0;
    const chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > maxBody) {
        res.writeHead(413, { 'content-type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ ok: false, error: '요청 본문이 너무 큽니다.' }));
        return;
      }
      chunks.push(chunk);
    }
    const method = req.method || 'GET';
    const headers = new Headers();
    for (const [key, value] of Object.entries(req.headers)) {
      if (Array.isArray(value)) value.forEach(item => headers.append(key, item));
      else if (value !== undefined) headers.set(key, value);
    }
    const request = new Request(new URL(req.url || '/', `http://${host}:${port}`), {
      method,
      headers,
      ...(!['GET', 'HEAD'].includes(method) && chunks.length
        ? { body: Buffer.concat(chunks) } : {}),
    });
    const response = await worker.fetch(request, process.env);
    res.statusCode = response.status;
    response.headers.forEach((value, key) => res.setHeader(key, value));
    if (method === 'HEAD') res.end();
    else res.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    if (!res.headersSent) {
      res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ ok: false, error: '서버 요청 처리에 실패했습니다.' }));
    } else res.end();
  }
});
server.on('error', () => {
  console.error('Development server could not start. Check the port and local permissions.');
  process.exitCode = 1;
});
server.listen(port, host, () => console.log(`Opportunity Radar: http://${host}:${port}`));
