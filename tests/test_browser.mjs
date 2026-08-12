/*
 * Exercises the browser-side target selection with a stub DOM, so the "one file
 * selected vs. fall back to the folder" branches are checked without a real browser.
 *
 * Run: node tests/test_browser.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const failures = [];

function check(label, condition, detail = "") {
  console.log(`[${condition ? "  ok  " : " FAIL "}] ${label}${detail ? `  -- ${detail}` : ""}`);
  if (!condition) failures.push(label);
}

/** Minimal stand-in for the parts of the DOM the scripts touch. */
function makeDom({ href, selected = [] }) {
  const nodes = selected.map((id) => ({
    getAttribute: (name) => (name === "data-id" ? id : null),
  }));
  let assigned = null;
  return {
    location: {
      get href() {
        return href;
      },
      set href(v) {
        assigned = v;
      },
    },
    document: {
      querySelectorAll: (sel) => (sel.includes("aria-selected") ? nodes : []),
      querySelector: () => null,
      body: { appendChild() {} },
      createElement: () => ({ style: {}, remove() {} }),
    },
    get assigned() {
      return assigned;
    },
  };
}

/** Run the bookmarklet against a stub DOM and return the URL it navigated to. */
function runBookmarklet(domSpec) {
  const source = readFileSync(join(ROOT, "bookmarklet", "bookmarklet.js"), "utf8");
  const dom = makeDom(domSpec);
  const sandbox = {
    document: dom.document,
    location: dom.location,
    encodeURIComponent,
    Object,
    RegExp,
  };
  vm.createContext(sandbox);
  new vm.Script(source).runInContext(sandbox);
  return dom.assigned;
}

const FOLDER_URL = "https://drive.google.com/drive/u/0/folders/1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI";
const FILE_ID = "1TKIylHD3-0Dt7gU6szxwSHH4MWzfLq6m";
const OTHER_ID = "1KlfSyff-hphr67x1qqPCgqgbiym8SBicarsn6VaZIXQ";

console.log("== bookmarklet target selection ==");

let got = runBookmarklet({ href: FOLDER_URL, selected: [] });
check(
  "nothing selected falls back to the page URL",
  got === `gdrivereveal://reveal?url=${encodeURIComponent(FOLDER_URL)}`,
  got,
);

got = runBookmarklet({ href: FOLDER_URL, selected: [FILE_ID] });
check(
  "one file selected uses that file's id",
  got === `gdrivereveal://reveal?id=${FILE_ID}`,
  got,
);

got = runBookmarklet({ href: FOLDER_URL, selected: [FILE_ID, FILE_ID] });
check(
  "same id twice still counts as one selection",
  got === `gdrivereveal://reveal?id=${FILE_ID}`,
  got,
);

got = runBookmarklet({ href: FOLDER_URL, selected: [FILE_ID, OTHER_ID] });
check(
  "multiple files selected falls back to the folder",
  got === `gdrivereveal://reveal?url=${encodeURIComponent(FOLDER_URL)}`,
  got,
);

got = runBookmarklet({ href: FOLDER_URL, selected: ["short", "x"] });
check(
  "junk data-id values are ignored",
  got === `gdrivereveal://reveal?url=${encodeURIComponent(FOLDER_URL)}`,
  got,
);

console.log("\n== syntax of shipped browser sources ==");
for (const rel of [
  ["extension", "content.js"],
  ["extension", "background.js"],
  ["bookmarklet", "bookmarklet.js"],
]) {
  const path = join(ROOT, ...rel);
  try {
    new vm.Script(readFileSync(path, "utf8"), { filename: path });
    check(`${rel.join("/")} parses`, true);
  } catch (e) {
    check(`${rel.join("/")} parses`, false, e.message);
  }
}

console.log("\n== extension manifest ==");
const manifest = JSON.parse(readFileSync(join(ROOT, "extension", "manifest.json"), "utf8"));
check("manifest is v2 (Firefox)", manifest.manifest_version === 2);
check("declares a gecko id", Boolean(manifest.browser_specific_settings?.gecko?.id));
check(
  "content script covers drive.google.com",
  manifest.content_scripts.some((cs) => cs.matches.includes("https://drive.google.com/*")),
);
check(
  "every referenced file exists",
  [
    ...manifest.background.scripts.map((f) => join(ROOT, "extension", f)),
    ...manifest.content_scripts.flatMap((cs) => cs.js.map((f) => join(ROOT, "extension", f))),
    ...Object.values(manifest.icons).map((f) => join(ROOT, "extension", f)),
  ].every((p) => {
    try {
      readFileSync(p);
      return true;
    } catch {
      return false;
    }
  }),
);

console.log();
if (failures.length) {
  console.log(`${failures.length} check(s) failed:`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log("all checks passed");
