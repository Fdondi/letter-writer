# Laya via Ollaya

[Laya](https://huggingface.co/convaiinnovations/laya) scores two things. The language model still writes the similarity bullets and the comments themselves.

- how similar each retrieved job is to the target job (the 1–10 score used to order RAG hits)
- whether a feedback comment is grounded in the letter, or a hallucination

When Laya marks a comment invalid, that comment leaves the open critique list and appears under the “already good” notes, with **Restore**.

Laya does not run inside the API process. The `ollaya` service in `docker-compose.yml` is [`ghcr.io/ollaya-dev/ollaya`](https://github.com/ollaya-dev/ollaya/pkgs/container/ollaya). On start it pulls the `laya` router (English and multilingual weights) into the `ollaya-models` volume, then serves `http://ollaya:11435`. The backend calls `POST /api/decide`.

If that container is down or the model was not pulled, RAG keeps the language-model score and feedback comments stay visible. The UI says that Laya did not score them, with the error from Ollaya.

The image listens on `0.0.0.0:11435` inside the compose network. That port is not published on the host.

Optional settings on the backend:

- `OLLAYA_BASE_URL` — default `http://ollaya:11435`.
- `LAYA_MODEL` — default `laya`, which routes English to `laya:en` and other languages to `laya:multilingual`. `laya:typed-decisions` is only used when set here.
- `LAYA_FEEDBACK_VALID_MIN` — grounded probability at or above this stays a critique (default `0.40`).
- `LAYA_FEEDBACK_INVALID_MIN_CONFIDENCE` — a low grounded probability is hidden only when confidence is at least this (default `0.55`). Uncertain comments stay in the open list.
- `OLLAYA_API_KEY` — sent as `Authorization: Bearer` when the Ollaya container requires a key.

On the Ollaya container, `OLLAYA_DEVICE` is `auto` (CPU on the default image). An NVIDIA GPU uses `OLLAYA_IMAGE=ghcr.io/ollaya-dev/ollaya:cuda` and the NVIDIA Container Toolkit. `:cuda12` is the tag for older drivers.
