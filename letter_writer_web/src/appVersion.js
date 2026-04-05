/**
 * UI version is read at runtime from the static asset `public/app-version.txt` (major.minor.patch).
 * It is not imported into the bundle, so changing the version does not alter JS module hashes or the build graph.
 */

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
  return (await res.text()).trim();
}
