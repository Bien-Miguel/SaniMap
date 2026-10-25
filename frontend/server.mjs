import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const distDirectory = resolve(fileURLToPath(new URL("./dist/", import.meta.url)));
const port = Number(process.env.PORT || 8080);
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function send(response, statusCode, body, contentType = "text/plain; charset=utf-8") {
  response.writeHead(statusCode, {
    "Content-Type": contentType,
    "X-Content-Type-Options": "nosniff",
  });
  response.end(body);
}

const server = createServer(async (request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.setHeader("Allow", "GET, HEAD");
    send(response, 405, "Method not allowed");
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(
      new URL(request.url, "http://localhost").pathname
    );
  } catch {
    send(response, 400, "Invalid URL");
    return;
  }

  const filePath = resolve(distDirectory, `.${pathname}`);
  if (
    filePath !== distDirectory &&
    !filePath.startsWith(`${distDirectory}${sep}`)
  ) {
    send(response, 403, "Forbidden");
    return;
  }

  try {
    let targetPath = filePath;
    let details = await stat(targetPath);
    if (details.isDirectory()) {
      targetPath = resolve(targetPath, "index.html");
      details = await stat(targetPath);
    }

    const contents = await readFile(targetPath);
    const extension = extname(targetPath).toLowerCase();
    const isIndex = targetPath === resolve(distDirectory, "index.html");
    response.writeHead(200, {
      "Content-Type": contentTypes[extension] || "application/octet-stream",
      "Content-Length": details.size,
      "Cache-Control": isIndex
        ? "no-cache"
        : "public, max-age=31536000, immutable",
      "X-Content-Type-Options": "nosniff",
    });
    response.end(request.method === "HEAD" ? undefined : contents);
  } catch (error) {
    if (error.code !== "ENOENT" && error.code !== "ENOTDIR") {
      console.error("Static file request failed:", error);
      send(response, 500, "Internal server error");
      return;
    }

    if (pathname.startsWith("/assets/")) {
      send(response, 404, "Not found");
      return;
    }

    try {
      const indexPath = resolve(distDirectory, "index.html");
      const contents = await readFile(indexPath);
      response.writeHead(200, {
        "Content-Type": contentTypes[".html"],
        "Content-Length": contents.length,
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
      });
      response.end(request.method === "HEAD" ? undefined : contents);
    } catch (fallbackError) {
      console.error("Frontend build output is unavailable:", fallbackError);
      send(response, 500, "Frontend build output is unavailable");
    }
  }
});

server.listen(port, "0.0.0.0", () => {
  console.log(`SaniMap frontend listening on port ${port}`);
});
