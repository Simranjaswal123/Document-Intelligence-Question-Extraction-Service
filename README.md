# Document Processing & Question Extraction API

A backend MVP that accepts uploaded question papers (and answer keys), extracts
structured questions from them using the Gemini API, and stores the results in
PostgreSQL. Built with FastAPI, Celery, Redis, and PostgreSQL.

## 1. How to Run

1. Set your Gemini API key as an environment variable:
   ```bash
   export GEMINI_API_KEY=your_key_here
   ```
2. Build and start all services:
   ```bash
   docker compose up --build
   ```
3. Open `http://localhost:8000/` for the web UI, or `http://localhost:8000/docs`
   for the interactive Swagger API docs. All `/api/v1/*` endpoints require an
   `X-API-KEY` header (default value: `changeme`, set via the `API_KEY`
   environment variable).

### Running Tests

With the `db` and `redis` containers already running (via `docker compose up`),
run in a separate terminal:
```bash
docker compose exec api pytest test_main.py -v
```

## 2. Project Structure

| File                    | Purpose                                                        |
|-------------------------|-----------------------------------------------------------------|
| `main.py`               | FastAPI app and route definitions                              |
| `tasks.py`              | Celery worker task that calls Gemini and extracts questions    |
| `models.py`             | SQLAlchemy models (`Document`, `ExtractedQuestion`) and DB setup |
| `requirements.txt`      | Python dependencies                                             |
| `Dockerfile`            | Container image definition for the API and worker              |
| `docker-compose.yml`    | Orchestrates `db`, `redis`, `api`, and `worker` services        |
| `test_main.py`          | Basic pytest tests using FastAPI's `TestClient`                 |
| `postman_collection.json` | Pre-filled Postman requests for manual API testing            |
| `sample_output.json`    | Example API response for a processed document                  |

## 3. Architecture

The system follows a simple async processing pipeline:

1. **FastAPI** receives an uploaded file at `POST /api/v1/upload`, saves it to
   a shared volume, and creates a `Document` row in **PostgreSQL** with status
   `PENDING`.
2. The request enqueues a job on **Redis** (used as the Celery message
   broker) and returns immediately with the document ID.
3. **Celery** worker picks up the job, marks the document `PROCESSING`,
   uploads the file to the **Gemini API**, and prompts it to return the
   extracted questions as structured JSON.
4. The worker parses the JSON response and saves each question as an
   `ExtractedQuestion` row, flagging any question with `confidence_score < 0.75`
   for manual review. The document status is then updated to `COMPLETED`
   (or `FAILED` if an error occurred).
5. If the document is linked to a question paper as an `ANSWER_KEY`, the
   worker also matches answers back to the original questions by
   `question_number`.
6. The client polls `GET /api/v1/documents/{id}/status` and then reads the
   results via the questions/review/answers endpoints.

```
Client → FastAPI (/upload) → PostgreSQL (Document row)
                            → Redis (enqueue task)
                                     ↓
                              Celery Worker → Gemini API
                                     ↓
                              PostgreSQL (ExtractedQuestion rows)
```

## 4. API Endpoints

| Method | Endpoint                                  | Purpose                                                        |
|--------|---------------------------------------------|-----------------------------------------------------------------|
| GET    | `/`                                          | Web UI (upload, status tracking, review items, linking)        |
| POST   | `/api/v1/upload`                             | Upload a document, create its DB record, and queue extraction  |
| GET    | `/api/v1/documents/{id}/status`              | Check the processing status of a document                      |
| GET    | `/api/v1/documents/{id}/questions`           | Get all extracted questions for a document                     |
| GET    | `/api/v1/questions/{id}`                     | Get a single extracted question by its ID                      |
| GET    | `/api/v1/documents/{id}/review-items`        | Get low-confidence questions flagged for manual review          |
| GET    | `/api/v1/documents/{id}/answers`             | Get extracted question numbers with their answers               |
| POST   | `/api/v1/documents/link`                     | Link a question paper to its answer key and trigger answer matching |

All `/api/v1/*` endpoints require an `X-API-KEY` header.

## 5. Trade-offs

For this MVP, the **Gemini Vision API** was used instead of a custom OCR
pipeline (e.g. Tesseract + manual layout parsing). Building a reliable
OCR + question-segmentation pipeline from scratch would require significant
time for handling scanned image quality, layout detection, and text
structuring — effort better spent on the core product flow given the
project timeline. Gemini can process PDFs/images directly and return
structured JSON in a single call, which made it the fastest path to a
working prototype. The trade-off is a dependency on an external API
(latency, cost, and rate limits) and less fine-grained control over
extraction accuracy compared to a purpose-built OCR pipeline.

**Async processing via Celery** decouples the slow, external AI call from the
HTTP request/response cycle entirely — uploads return immediately instead of
blocking for however long extraction takes. The worker also retries on
transient Gemini server errors and rate limits (a couple of short backoff
attempts) before giving up, so a temporary API hiccup doesn't fail an
otherwise-good document.

**Confidence is grounded in legibility, not plausibility.** The extraction
prompt explicitly instructs the model to score `confidence_score` based on
how certain it is of what it actually read, not how coherent the guessed
text sounds — and to mark illegible regions as such rather than inventing
plausible-sounding content. This was a deliberate fix after testing showed
the model could otherwise hallucinate fluent, high-confidence answers for
genuinely unreadable scans.
