# Gmail Scanner

Personal Gmail ingestion app focused only on the user's own job application emails.

It imports emails from Gmail, stores them in SQLite, and keeps only application-related states:

- `application`
- `rejection`
- `interview`
- `offer`

Recruiter outreach, job alerts, recommendations, newsletters, and marketing emails are intentionally excluded.

## Current flow

1. Fetch messages from Gmail using OAuth and a Gmail search query.
2. Normalize subject/body content.
3. Run deterministic subject classification first.
4. If subject is unclear, run deterministic body classification.
5. If still unclear, use Ollama as a final fallback.
6. Store every imported email in `Emails`.
7. Create a `JobApplications` row only when the email is one of the tracked application states.
8. Group application events into `JobApplicationEntities` (company-level grouping) and link emails via `JobApplicationEntityEmails`.

## Database schema

The app uses 4 tables:

- `Emails`
  - raw imported emails
  - includes `classification`, which is nullable
- `JobApplications`
  - created only for `application`, `rejection`, `interview`, or `offer`
  - linked back to `Emails` through `email_id`
- `JobApplicationEntities`
  - grouped “application entities” per company (and optional role)
  - stores aggregate status + dates (`first_email_date`, `last_email_date`)
- `JobApplicationEntityEmails`
  - link table (`entity_id`, `email_id`) connecting imported emails to grouped entities

If `Emails.classification` is `null`, that means the email was imported but not considered one of the tracked application states.

## API endpoints

- `GET /health`
- `GET /emails`
- `GET /job-applications`
- `GET /job-application-entities`
- `GET /job-application-entity-emails`
- `POST /ingest/run`

Open `http://127.0.0.1:8000/docs` for Swagger UI.

## Performance + safety guards

- **Global ingestion lock**: only one `POST /ingest/run` runs at a time. If another ingest is running, the endpoint returns a “busy” response with zeros.
- **Global Ollama single-flight**: all Ollama calls are serialized (max 1 at a time) to avoid overheating / fan spikes during large ingests.
- **In-run memoization**: if an email already used Ollama during classification, entity extraction will reuse that result when possible.

Locks are file-based and live in `/tmp` (local machine only):

- `/tmp/gmail_scanner_ingest.lock`
- `/tmp/gmail_scanner_ollama.lock`

## Setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
poetry install
```

3. Copy environment variables:

```bash
cp .env.example .env
```

4. Configure Gmail OAuth:

- Create a Google Cloud OAuth client.
- Download the OAuth credentials file.
- Save it as `client_secret.json` in the project root, or update `GOOGLE_CLIENT_SECRET_FILE` in `.env`.
- Make sure your Google account is allowed in the OAuth consent screen test users.

5. Configure the default Gmail fetch window in `.env`:

```env
GMAIL_SEARCH_QUERY=in:inbox category:primary newer_than:10d
GMAIL_MAX_RESULTS_PER_POLL=50
```

This means the app currently reads only Primary inbox emails from the last 10 days, up to 50 per ingest run.

6. Start Ollama if you want LLM fallback enabled:

```bash
ollama serve
ollama pull llama3:latest
```

7. Start the API server:

```bash
poetry run uvicorn app.main:app --reload
```

Or:

```bash
./.venv/bin/uvicorn app.main:app --reload
```

## Environment variables

Main settings from `.env.example`:

```env
DATABASE_URL=sqlite:///./app.db
GOOGLE_CLIENT_SECRET_FILE=./client_secret.json
GOOGLE_TOKEN_FILE=./gmail_token.json
GMAIL_USER_ID=me
GMAIL_SEARCH_QUERY=in:inbox category:primary newer_than:10d
GMAIL_MAX_RESULTS_PER_POLL=50
USE_LLM=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest
```

Optional app behavior:

- `RESET_DB_ON_START=true` will drop and recreate tables on app startup.
- Leave it `false` for normal usage.

## Backfill (improve old NULL company/role)

If your `JobApplications.matched_company` / `matched_role` fields have many `null` values, you can safely enrich historical rows (fills only missing values):

```bash
./.venv/bin/python -m app.services.backfill_company_role
```

## Notes

- The first Gmail OAuth flow will create `gmail_token.json`.
- The first app run will create `app.db`.
- If you want a clean re-test from scratch, delete `app.db` and ingest again.
- If you change the schema significantly, it is usually easiest to delete `app.db` and re-import.

## GitHub safety

Do not commit these local files:

- `.env`
- `client_secret.json`
- `gmail_token.json`
- `app.db`
- any local logs, caches, or virtualenv files

Before pushing, check:

```bash
git status
```

Make sure no secrets, tokens, or SQLite database files are staged.

