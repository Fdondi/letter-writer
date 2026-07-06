# Language and typography

The author types German with proper umlauts. Default German language instructions (Settings → languages) include the umlaut rule; user-facing German text should use **ä, ö, ü, ß** — never ASCII stand-ins like `Fuer`/`fuer` unless explicitly requested (e.g. URL slugs).

Per-language CEFR levels and instructions live in Firestore `personal_data.default_languages[]` (`level`, `instructions`) and are injected into LLM generation and LLM translation.

# Version

Update version in: `letter_writer_web/public/app-version.txt`

(changelog, newest first: `<major.minor.patch> - <description>` per line; UI shows only the first line's version; loader: `letter_writer_web/src/appVersion.js`)

`AGENT.md` is documentation only — changing it does not change the reported app version.
