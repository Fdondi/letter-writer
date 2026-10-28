#!/usr/bin/env bash
# Enable Firebase on the existing GCP project and register the Android app.
#
# Prerequisites: `gcloud auth login` (project owner) and `firebase login` with the same account.
# Run from the repo root:  bash scripts/firebase/setup_android_firebase.sh
#
# What it does (all idempotent; "already exists" errors are reported and skipped):
#   1. Enables the Firebase, Identity Toolkit and Secure Token APIs.
#   2. Adds Firebase to the project.
#   3. Registers the Android app io.github.fdondi.letterwriter and adds the debug SHA-1.
#   4. Downloads google-services.json into app/app/ (gitignored).
#   5. Deploys firebase/firestore.rules to the `letter` database.
#
# Console steps it cannot do (printed at the end):
#   - Authentication → Sign-in method → enable Google. The CLI fingerprint
#     does not create the Android OAuth client; until Google is enabled,
#     sign-in fails with UNREGISTERED_ON_API_CONSOLE.
#   - OAuth consent screen: keep in Testing, add your account as test user,
#     add scopes bigquery.insertdata and bigquery.readonly.
set -euo pipefail

PROJECT="${PROJECT:-gen-lang-client-0535858734}"
PACKAGE="io.github.fdondi.letterwriter"
DISPLAY_NAME="Letter Writer Android"
KEYSTORE="${KEYSTORE:-$HOME/.android/debug.keystore}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

step() { printf '\n== %s\n' "$*"; }

step "Enabling APIs"
gcloud services enable firebase.googleapis.com identitytoolkit.googleapis.com securetoken.googleapis.com --project "$PROJECT"

step "Adding Firebase to $PROJECT"
firebase projects:addfirebase "$PROJECT" || echo "addfirebase failed (already a Firebase project?) - continuing"

step "Registering Android app $PACKAGE"
find_app_id() {
  firebase apps:list ANDROID --project "$PROJECT" --json | python3 -c "import json,sys; apps=json.load(sys.stdin).get('result',[]); print(next((a['appId'] for a in apps if a.get('packageName')=='$PACKAGE'),''))"
}
APP_ID="$(find_app_id)"
if [ -z "$APP_ID" ]; then
  firebase apps:create ANDROID "$DISPLAY_NAME" --package-name "$PACKAGE" --project "$PROJECT"
  APP_ID="$(find_app_id)"
fi
if [ -z "$APP_ID" ]; then
  echo "Could not find the Android app after creating it" >&2
  exit 1
fi
echo "App id: $APP_ID"

step "Adding SHA-1 from $KEYSTORE"
SHA1="$(keytool -list -v -keystore "$KEYSTORE" -alias androiddebugkey -storepass android -keypass android | awk '/SHA1:/ {print $2}')"
if [ -z "$SHA1" ]; then
  echo "No SHA-1 found in $KEYSTORE" >&2
  exit 1
fi
firebase apps:android:sha:create "$APP_ID" "$SHA1" --project "$PROJECT" || echo "SHA-1 already registered - continuing"
SHA256="$(keytool -list -v -keystore "$KEYSTORE" -alias androiddebugkey -storepass android -keypass android | awk '/SHA256:/ {print $2}')"
firebase apps:android:sha:create "$APP_ID" "$SHA256" --project "$PROJECT" || echo "SHA-256 already registered - continuing"

step "Downloading google-services.json"
firebase apps:sdkconfig ANDROID "$APP_ID" --project "$PROJECT" -o "$ROOT/app/app/google-services.json"

step "Deploying Firestore rules (database: letter)"
(cd "$ROOT/firebase" && firebase deploy --only firestore --project "$PROJECT")

cat <<EOF

Done. Remaining console steps:
  1. https://console.firebase.google.com/project/$PROJECT/authentication/providers
     Enable "Google". That step creates the Android OAuth client for the
     registered SHA-1. Without it, sign-in fails with UNREGISTERED_ON_API_CONSOLE.
     Copy the "Web client ID" it shows into app/local.properties as
     letterwriter.webClientId=<id>
     The web client is a normal sign-in client: leave "Use this client for an
     AI-powered agent" unchecked (that option is for agents calling Google APIs
     via MCP, not for user sign-in).
  2. https://console.cloud.google.com/auth/audience?project=$PROJECT
     Keep "Testing", add your Google account as a test user.
  3. https://console.cloud.google.com/auth/scopes?project=$PROJECT
     Add https://www.googleapis.com/auth/bigquery.insertdata and
     https://www.googleapis.com/auth/bigquery.readonly
  4. Seed your API keys (optional, otherwise set them in the app's Settings):
     temp/venv/bin/python scripts/firebase/seed_api_keys.py --user-id <google sub>
EOF
