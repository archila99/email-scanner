# Gmail Scanner (Intelligent Job Application Tracker)

Personal job application email checker.

## What this MVP does

- Pulls emails from Gmail (OAuth) using Gmail API
- Applies hard-block noise filtering (domains + unsubscribe/newsletter/promo patterns)
- Uses a local LLM (Ollama) to categorize job-related emails and extract structured fields:
  - categories: `application_received`, `rejected`, `interview`, `offer`
  - extracts `company` and `role`
- Tracks applications in SQLite keyed by `company + role`
- Runs an automation engine that can generate “follow-up/notify” actions as audit records

## Setup

1. Install dependencies (recommended: project venv so imports match `uvicorn`):
   - `python3 -m venv .venv`
   - `source .venv/bin/activate` (Windows: `.venv\\Scripts\\activate`)
   - `pip install -r requirements.txt`
   - Or Poetry: `poetry install`
2. Copy environment template:
   - `cp .env.example .env`
3. Configure Gmail OAuth:
   - Create a Google Cloud OAuth Client
   - Download `client_secret.json`
   - Set `GOOGLE_CLIENT_SECRET_FILE` to it
   - In OAuth Consent Screen (Testing), add yourself as a Test User to avoid `Error 403: access_denied`
4. Install and run Ollama (local/free LLM):
   - Install Ollama: `brew install ollama` (or download from Ollama site)
   - Start Ollama: `ollama serve`
   - Pull a model: `ollama pull llama3:latest` (or another installed model)
   - Ensure `.env` has `USE_LLM=true` and `OLLAMA_MODEL` matches your local model name
5. Start the server (with venv activated, or use the full path below):
    - `./.venv/bin/uvicorn app.main:app --reload`
    - Poetry: `poetry run uvicorn app.main:app --reload`

## Common endpoints

- `GET /health`
- `POST /ingest/run` (poll and process new emails)
- `POST /applications` (add a company+role to track)
- `GET /applications`
- `GET /automation/actions`

## Notes

- Do not commit secrets or tokens. Keep these local only:
  - `.env`
  - `client_secret.json`
  - `gmail_token.json`
  - `app.db`
- Email sending (follow-ups) is not implemented in this MVP. Automation actions are recorded for review.
- Once OAuth is set, the first ingest run will create the SQLite DB.
- Schema note: if you already created `app.db` before enabling LLM extraction fields, delete `app.db` and re-ingest.

## Pushing to GitHub

From the project root:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

