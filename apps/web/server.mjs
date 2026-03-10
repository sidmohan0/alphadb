import { createReadStream, existsSync, statSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.join(__dirname, "dist");
const indexHtmlPath = path.join(distDir, "index.html");
const port = Number(process.env.PORT || 8080);

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain; charset=utf-8"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

function setHeaders(response, pathname) {
  if (pathname === "/runtime-config.js") {
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "text/javascript; charset=utf-8");
    return;
  }

  if (pathname.startsWith("/assets/")) {
    response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    return;
  }

  response.setHeader("Cache-Control", "no-cache");
}

function runtimeConfigSource() {
  return `window.__ALPHADB_CONFIG__ = Object.assign({}, window.__ALPHADB_CONFIG__ || {}, ${JSON.stringify({
    apiBaseUrl: process.env.ALPHADB_WEB_API_BASE_URL?.trim() || "",
  })});\n`;
}

function sendFile(response, filePath, pathname) {
  const extension = path.extname(filePath);
  response.statusCode = 200;
  response.setHeader("Content-Type", contentTypes.get(extension) || "application/octet-stream");
  setHeaders(response, pathname);
  createReadStream(filePath).pipe(response);
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || "/", "http://localhost");
  const pathname = decodeURIComponent(url.pathname);

  if (pathname === "/health") {
    response.statusCode = 200;
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.end(JSON.stringify({ ok: true, service: "alphadb-web" }));
    return;
  }

  if (pathname === "/runtime-config.js") {
    response.statusCode = 200;
    setHeaders(response, pathname);
    response.end(runtimeConfigSource());
    return;
  }

  const resolvedPath = path.join(distDir, pathname === "/" ? "index.html" : pathname.slice(1));
  const normalizedPath = path.normalize(resolvedPath);
  if (!normalizedPath.startsWith(distDir)) {
    response.statusCode = 403;
    response.end("Forbidden");
    return;
  }

  if (existsSync(normalizedPath) && statSync(normalizedPath).isFile()) {
    sendFile(response, normalizedPath, pathname);
    return;
  }

  try {
    const indexHtml = await readFile(indexHtmlPath, "utf8");
    response.statusCode = 200;
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    setHeaders(response, pathname);
    response.end(indexHtml);
  } catch {
    response.statusCode = 500;
    response.end("Failed to load AlphaDB web bundle.");
  }
});

server.listen(port, "0.0.0.0", () => {
  console.log(`AlphaDB web listening on http://0.0.0.0:${port}`);
});
