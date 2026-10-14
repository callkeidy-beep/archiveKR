import worker from "../worker/index.js";

export default async function handler(req, res) {
  const url = new URL(req.url || "/", `https://${req.headers.host || "localhost"}`);
  const method = req.method || "GET";
  const headers = new Headers(req.headers);
  let body;
  if (method !== "GET" && method !== "HEAD" && req.body !== undefined) {
    body = typeof req.body === "string" ? req.body : JSON.stringify(req.body);
    headers.set("content-type", "application/json");
  }
  const request = new Request(url, { method, headers, body });
  const response = await worker.fetch(request, process.env);
  res.statusCode = response.status;
  response.headers.forEach((value, key) => res.setHeader(key, value));
  res.end(await response.text());
}
