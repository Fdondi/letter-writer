/**
 * UI version is read at runtime from the static asset `public/app-version.txt`.
 * File format (newest first): `<major.minor.patch> - <description>` per line.
 * Only the version from the first non-empty line is shown in the UI.
 * It is not imported into the bundle, so changing the version does not alter JS module hashes or the build graph.
 */

const VERSION_LINE_RE = /^(\d+\.\d+\.\d+)\s*-\s*.+$/;

export function parseAppVersionText(raw) {
  const line = raw
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .find((entry) => entry.length > 0);
  if (!line) throw new Error("app-version.txt: empty file");
  const match = line.match(VERSION_LINE_RE);
  if (!match) {
    throw new Error(`app-version.txt: invalid first line (expected "<version> - <text>"): ${JSON.stringify(line)}`);
  }
  return match[1];
}

export function getAppVersionUrl() {
  let base = "/";
  if (typeof document !== "undefined") {
    const fromDom = document.documentElement?.dataset?.viteBaseUrl;
    if (typeof fromDom === "string" && fromDom.length > 0) {
      base = fromDom;
    }
  }
  return `${base}app-version.txt`;
}

export async function fetchAppVersion(signal) {
  const res = await fetch(getAppVersionUrl(), { cache: "no-store", signal });
  if (!res.ok) throw new Error(`app-version.txt: ${res.status}`);
  return parseAppVersionText(await res.text());
}
