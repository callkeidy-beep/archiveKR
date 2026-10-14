import { readFileSync, writeFileSync } from "node:fs";
const html = readFileSync(new URL("../app/index.html", import.meta.url), "utf8");
const template = readFileSync(new URL("../worker/entry-template.mjs", import.meta.url), "utf8");
writeFileSync(new URL("../worker/index.js", import.meta.url), template.replace("__PAGE_JSON__", () => JSON.stringify(html)));
