// Builds pwa/ (the stlite static deployment output) from app/.
//
// This script is the ONLY place that needs to know how app/ is structured.
// It walks app/ itself and copies whatever it finds into pwa/app/, then
// auto-generates the stlite `files` map from that same walk. Nobody has to
// hand-edit a file list in index.html when a new page/asset is added to
// app/ - re-running this script (which Vercel does on every build) picks
// it up automatically.
//
// Usage: node scripts/build-pwa.mjs

import { existsSync, mkdirSync, readdirSync, statSync, copyFileSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const APP_SRC = path.join(REPO_ROOT, "app");
const PWA_OUT = path.join(REPO_ROOT, "pwa");
const PWA_APP_OUT = path.join(PWA_OUT, "app");

// stlite's Pyodide file system only needs to see files the app actually
// reads at runtime (Python source, stylesheets, icons). Anything else in
// app/ (e.g. __pycache__) is noise we should not ship to the browser.
const ALLOWED_EXTENSIONS = new Set([
  ".py",
  ".css",
  ".svg",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
  ".ico",
  ".json",
]);
const SKIP_DIR_NAMES = new Set(["__pycache__", "node_modules"]);

// Confirmed against the official stlite README (github.com/whitphx/stlite,
// section "Use Stlite on your web page"): the `mount()` browser API is at
// this CDN path/version, and requirements only needs packages that are
// actually installed via micropip - `streamlit` itself is bundled by
// stlite and any `streamlit` entry in `requirements` is ignored, per the
// stlite CHANGELOG ("`streamlit` requirement is allowed but ignored").
const STLITE_VERSION = "1.8.1";

function walk(dir, relBase, out) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue; // dotfiles/.gitkeep, nothing app/ reads at runtime
    const abs = path.join(dir, entry.name);
    const rel = path.posix.join(relBase, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIR_NAMES.has(entry.name)) continue;
      walk(abs, rel, out);
    } else if (entry.isFile()) {
      if (ALLOWED_EXTENSIONS.has(path.extname(entry.name))) {
        out.push(rel);
      }
    }
  }
}

function main() {
  if (!existsSync(APP_SRC)) {
    throw new Error(`app/ not found at ${APP_SRC}`);
  }

  // Rebuild pwa/app/ from scratch each time so removed source files don't
  // linger as stale copies in the deployed bundle.
  rmSync(PWA_APP_OUT, { recursive: true, force: true });
  mkdirSync(PWA_APP_OUT, { recursive: true });

  const relFiles = [];
  walk(APP_SRC, "", relFiles);
  relFiles.sort();

  const filesManifest = {};
  for (const rel of relFiles) {
    const srcPath = path.join(APP_SRC, rel);
    const destPath = path.join(PWA_APP_OUT, rel);
    mkdirSync(path.dirname(destPath), { recursive: true });
    copyFileSync(srcPath, destPath);
    // Relative URL loading (files: {"...": {url: "./..."}}) is the
    // officially documented way to avoid inlining source as JS strings.
    filesManifest[`app/${rel}`] = { url: `./app/${rel}` };
  }

  // 브라우저에서는 환경변수를 읽을 수 없으므로, 백엔드 주소를 빌드 시점에
  // 설정 파일로 구워 넣는다. Vercel 프로젝트 설정의 THERMOSHIFT_API_BASE
  // 환경변수를 그대로 쓴다. 비어 있으면 app/components/backend.py 가
  // API를 끄고 로컬 목데이터로 동작한다.
  const apiBase = (process.env.THERMOSHIFT_API_BASE || "").replace(/\/$/, "");
  const apiConfigPath = path.join(PWA_APP_OUT, "api_config.json");
  writeFileSync(apiConfigPath, JSON.stringify({ api_base: apiBase }, null, 2), "utf8");
  filesManifest["app/api_config.json"] = { url: "./app/api_config.json" };
  console.log(
    apiBase
      ? `[build-pwa] api_base = ${apiBase}`
      : "[build-pwa] api_base 미설정 - 목데이터 모드로 동작합니다",
  );

  const indexHtml = renderIndexHtml(filesManifest);
  writeFileSync(path.join(PWA_OUT, "index.html"), indexHtml, "utf8");

  console.log(`[build-pwa] copied ${relFiles.length} files from app/ into pwa/app/`);
  console.log(`[build-pwa] wrote pwa/index.html (stlite @${STLITE_VERSION})`);
}

function renderIndexHtml(filesManifest) {
  const filesJson = JSON.stringify(filesManifest, null, 2);
  return `<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
    <title>ThermoShift</title>
    <link
      rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/@stlite/browser@${STLITE_VERSION}/build/stlite.css"
    />
    <script
      type="module"
      src="https://cdn.jsdelivr.net/npm/@stlite/browser@${STLITE_VERSION}/build/stlite.js"
    ></script>
    <style>
      html, body, #root { height: 100%; margin: 0; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module">
      import { mount } from "https://cdn.jsdelivr.net/npm/@stlite/browser@${STLITE_VERSION}/build/stlite.js";

      // Auto-generated by scripts/build-pwa.mjs from app/ - do not edit by hand.
      const files = ${filesJson};

      mount(
        {
          // requests 는 Pyodide에서 소켓을 못 써 동작하지 않는다.
          // app/components/backend.py 가 이를 감지해 동기 XMLHttpRequest
          // 전송으로 자동 전환하므로, 여기에 추가하지 않는다.
          requirements: [],
          entrypoint: "app/main.py",
          files,
          streamlitConfig: {
            "client.toolbarMode": "minimal",
          },
          // Persists app/components/*_store.py's .data/*.json across page
          // reloads (default Pyodide FS is in-memory and would otherwise
          // reset all mock data - registered users/rooms/logs - on every
          // reload). stlite mounts app files under the pyodide home
          // directory (confirmed via console log: "Write a file
          // /home/pyodide/app/..."), and Path(__file__).resolve().parents[2]
          // from app/components/*.py resolves to that same home dir, so
          // ".data" ends up at /home/pyodide/.data - not /.data.
          idbfsMountpoints: ["/home/pyodide/.data"],
        },
        document.getElementById("root"),
      );
    </script>
  </body>
</html>
`;
}

main();
