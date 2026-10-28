#!/usr/bin/env bash
# Package the job-capture extension for distribution (docs/JOB_CAPTURE_EXTENSION.md).
#
#   ./package.sh [download-base-url] [--sign]
#
# The download-base-url is only used for the self-hosted CRX (update.xml + the force-install
# policy below); the Firefox xpi and the store zip are built without it — omit it and a
# placeholder stays in update.xml, unused. AMO credentials for --sign are read from .env next
# to this script when WEB_EXT_API_KEY / WEB_EXT_API_SECRET are not already set.
#
# Builds in dist/:
#   letter-writer-capture-<version>.zip         Chrome Web Store / Edge Add-ons upload
#   letter-writer-capture-<version>.xpi         Firefox: UNSIGNED — sign on AMO first (see below);
#                                               release Firefox rejects unsigned packages
#   letter-writer-capture-<version>.crx         self-hosted Chrome/Edge install, no Developer mode
#   update.xml                                  update manifest for the CRX + ExtensionInstallForcelist
#   letter-writer-capture-<version>.signed.xpi  with --sign: AMO-signed (unlisted), installable
#                                               in Firefox as-is (needs WEB_EXT_API_KEY/WEB_EXT_API_SECRET)
#
# The CRX signing key lives in keys/ (gitignored): keep it — losing it changes the extension ID
# and every installed copy would have to be reinstalled.
set -euo pipefail

cd "$(dirname "$0")"
version=$(python3 -c 'import json; print(json.load(open("manifest.json"))["version"])')
name="letter-writer-capture"
dist="dist"
stage="$dist/stage"
keys="keys"

sign=false
base="https://example.invalid/extensions"
base_given=false
for arg in "$@"; do
  case "$arg" in
    --sign) sign=true ;;
    *) base="$arg"; base_given=true ;;
  esac
done

# AMO API credentials for --sign: load .env (gitignored) next to this script when the
# variables are not already set in the environment.
if [ -z "${WEB_EXT_API_KEY:-}" ] && [ -z "${WEB_EXT_API_SECRET:-}" ] && [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

rm -rf "$dist"
mkdir -p "$stage" "$keys"

# Runtime files only: the examples/ HTML fixtures and the tests are development-only.
cp manifest.json background.js pending.js pipeline.js firestore.js options.html options.js "$stage/"
cp -r icons "$stage/icons"

( cd "$stage" && zip -q -r -X "../$name-$version.zip" . )
cp "$dist/$name-$version.zip" "$dist/$name-$version.xpi"

finish() {
  echo "Built in $dist/:"
  echo "  $name-$version.zip   Chrome Web Store / Edge Add-ons upload"
  echo "  $name-$version.xpi   Firefox: UNSIGNED — release Firefox rejects it; sign on AMO first"
  if [ -f "$dist/$name-$version.crx" ]; then
    echo "  $name-$version.crx   self-hosted install (no Developer mode)"
    echo "  update.xml           update manifest for the CRX"
    echo "Extension ID: ${appid:-unknown} (verify on chrome://extensions after the first install)"
    echo "Force-install policy (Linux: /etc/opt/chrome/policies/managed/ or /etc/opt/edge/policies/managed/):"
    echo "  {\"ExtensionInstallForcelist\": [\"${appid:-unknown};$base/update.xml\"]}"
  fi
  if [ -f "$dist/$name-$version.signed.xpi" ]; then
    echo "  $name-$version.signed.xpi   Firefox: AMO-signed (unlisted) — install this file as-is"
  fi
}

# --- self-hosted CRX (Chrome/Edge, no Developer mode) -------------------------------

chrome_cmd=()
for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then chrome_cmd=("$candidate"); break; fi
done
if [ ${#chrome_cmd[@]} -eq 0 ] && command -v flatpak >/dev/null 2>&1; then
  # Chrome as a Flatpak (no google-chrome on PATH). The sandbox has no home access by default;
  # grant it for this one run so Chrome can read the staging dir and write the CRX and key.
  for app in com.google.Chrome org.chromium.Chromium; do
    if flatpak info "$app" >/dev/null 2>&1; then chrome_cmd=(flatpak run --filesystem=home "$app"); break; fi
  done
fi

if [ ${#chrome_cmd[@]} -eq 0 ]; then
  echo "No Chrome/Chromium found (PATH: google-chrome, chromium; Flatpak: com.google.Chrome, org.chromium.Chromium): skipped the CRX."
else
  pem="$keys/$name.pem"
  pack_args=(--pack-extension="$stage" --pack-extension-key="$pem" --no-sandbox --disable-gpu)
  if [ ! -f "$pem" ]; then
    # First run: let Chrome generate the key, then keep it in keys/.
    pack_args=(--pack-extension="$stage" --no-sandbox --disable-gpu)
  fi
  "${chrome_cmd[@]}" "${pack_args[@]}" >/dev/null 2>&1
  if [ ! -f "$dist/stage.crx" ]; then
    echo "CRX packing failed." >&2
    if [ "${chrome_cmd[0]}" = "flatpak" ]; then
      echo "The Flatpak sandbox needs home access for the run (the script adds --filesystem=home);" >&2
      echo "the repo must live under your home directory, e.g. ${HOME}/..." >&2
    fi
    exit 1
  fi
  mv "$dist/stage.crx" "$dist/$name-$version.crx"
  if [ ! -f "$pem" ] && [ -f "$dist/stage.pem" ]; then mv "$dist/stage.pem" "$pem"; fi

  # Extension ID: first 128 bits of the SHA-256 of the public key, hex digits mapped a-p.
  hex=$(openssl rsa -in "$pem" -pubout -outform DER 2>/dev/null | openssl dgst -sha256 | awk '{print $NF}')
  appid=$(printf '%s' "$hex" | cut -c1-32 | tr '0123456789abcdef' 'abcdefghijklmnop')

  cat > "$dist/update.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">
  <app appid="$appid">
    <updatecheck codebase="$base/$name-$version.crx" version="$version" />
  </app>
</gupdate>
EOF
  if [ "$base_given" = false ]; then
    echo "Note: no download-base-url given — update.xml keeps the placeholder ($base); it is"
    echo "only read by self-hosted Chrome/Edge installs. The Firefox xpi and the store zip"
    echo "do not use it."
  fi
fi

# --- AMO signing (Firefox) ----------------------------------------------------------
# Release Firefox only installs AMO-signed add-ons; this turns the unsigned xpi into the
# installable signed one. Credentials: addons.mozilla.org → Developer Hub → Manage API Keys.
if [ "$sign" = true ]; then
  if [ -z "${WEB_EXT_API_KEY:-}" ] || [ -z "${WEB_EXT_API_SECRET:-}" ]; then
    echo "Signing needs AMO API credentials in WEB_EXT_API_KEY / WEB_EXT_API_SECRET" >&2
    echo "(addons.mozilla.org → Developer Hub → Manage API Keys). Put them in .env next to" >&2
    echo "this script (gitignored) or pass them inline." >&2
    exit 1
  fi
  echo "Signing with AMO (unlisted)…"
  npx --yes web-ext sign --source-dir "$stage" \
    --api-key "$WEB_EXT_API_KEY" --api-secret "$WEB_EXT_API_SECRET" \
    --channel unlisted --artifacts-dir "$dist/web-ext-artifacts"
  signed=$(find "$dist/web-ext-artifacts" -name '*.xpi' | head -1)
  [ -n "$signed" ] || { echo "AMO signing produced no xpi" >&2; exit 1; }
  mv "$signed" "$dist/$name-$version.signed.xpi"
fi

finish
