# Backend

Person A backend service for the C group medical annotation platform.

## Run Locally

From the project root:

```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/docs
```

## Implemented Day2 Endpoints

```text
POST /api/upload
GET  /api/cases
GET  /api/case/{case_id}
GET  /api/image/{image_id}
GET  /api/health
```

The current implementation uses temporary JSON files:

```text
database/dev_cases.json
database/dev_images.json
```

These files are runtime data and are ignored by Git. They can later be replaced by SQLite or PostgreSQL without changing the public API contract.

