# Video Script — Document Processing & Question Extraction Service

Target length: **2:50–3:00**. Read at a measured, confident pace (~130 wpm).

---

## [0:00 – 0:18] — Introduction & Architecture

**ON SCREEN:** Title/dashboard UI at `http://localhost:8000/` (empty state).

**VOICEOVER:**
"Hi, I'm [Your Name]. This is my Document Processing and Question Extraction Service — it takes a scanned question paper and turns it into structured, queryable data. It's built on FastAPI, PostgreSQL, Redis and Celery, with Google's Gemini vision-capable model doing the actual reading and understanding."

---

## [0:18 – 0:48] — Demo 1: Standard Upload & Async Processing

**ON SCREEN:** Upload a clean PDF (`Question_Paper.pdf`) via the dashboard. Immediately after clicking upload, switch to a terminal showing `docker logs pnbc-api-1` with the `200 OK` response and `{"status": "PENDING"}`. Then show the status pill ticking PENDING → PROCESSING → COMPLETED.

**VOICEOVER:**
"I'll upload a question paper. Notice the API responds immediately — it doesn't wait for the AI to finish. It just saves the file, queues a background job, and returns a document ID with status PENDING right away. The actual extraction happens asynchronously in a separate Celery worker, so the HTTP request is never blocked."

---

## [0:48 – 1:08] — Demo 2: Image & Scanned Inputs

**ON SCREEN:** Upload a `.jpg` scanned page, then upload `scanned_lowquality.jpg` — a deliberately low-quality scan.

**VOICEOVER:**
"It's not limited to clean PDFs. Here's a photographed page, and here's a genuinely low-quality, blurry scan. Because Gemini reads these as images rather than running fixed OCR rules, it handles messy real-world scans instead of just clean text layers."

---

## [1:08 – 1:33] — Demo 3: Structured Extraction & Multi-Page Split

**ON SCREEN:** Open the completed document's questions view (or Swagger `/docs` → `GET /api/v1/documents/{id}/questions`). Scroll to a question with `"source_pages": [1, 2]`.

**VOICEOVER:**
"Once processing completes, every question comes back as structured JSON — question text, multiple-choice options, and source page numbers. Here's a good example: this question actually started on page one and continued onto page two, and the system correctly tags it with source pages 1 and 2 instead of splitting it into two broken questions."

---

## [1:33 – 1:53] — Demo 4: Confidence & Human Review Mechanism

**ON SCREEN:** Switch to the "Review Required Items" tab, load a document ID, show the red-bordered card with `confidence_score: 0.5`.

**VOICEOVER:**
"Not every extraction is equally certain. Every question gets a confidence score, and anything below 0.75 is automatically flagged as `review_required`. This one scored 0.5 because the source text was intentionally garbled — instead of silently trusting a bad read, the system routes it to a human review queue."

---

## [1:53 – 2:23] — Demo 5: Answer Key Association

**ON SCREEN:** Upload `Answer_Key.pdf` as doc type ANSWER_KEY. Open the Link modal, select the question paper and answer key from Recent Uploads. Submit. Then reload the question paper's questions view showing populated `answer` fields.

**VOICEOVER:**
"Here's the answer key. I upload it, then link it to the original question paper through this modal — under the hood that's a call to `/documents/link`. The system matches each answer back to its question by question number, even when the two documents format question numbers slightly differently, and populates the resolved answer directly onto the original questions — no manual pairing needed."

---

## [2:23 – 2:45] — Key Engineering Decisions & Trade-offs

**ON SCREEN:** Split view or quick cut to `tasks.py` in the editor, briefly highlighting the retry loop.

**VOICEOVER:**
"Two decisions I'd call out: I chose a vision LLM over traditional OCR-plus-regex because exam papers vary wildly in layout — a brittle regex pipeline breaks the moment formatting changes, while the model just reads it. And Celery decouples the slow AI call from the request cycle entirely, with retry logic for transient rate-limit or server errors, so one flaky API response doesn't fail an entire document."

---

## [2:45 – 2:55] — Conclusion

**ON SCREEN:** Quick cut to GitHub repo page, then `postman_collection.json` and `sample_output.json` in the file tree, then a terminal running `docker compose up`.

**VOICEOVER:**
"Everything here — the code, a Postman collection, and a sample output file — is in the GitHub repo, and the whole stack runs with a single `docker compose up`. Thanks for watching."

---

## Pre-recording checklist

- [ ] Have `Question_Paper.pdf`, `Answer_Key.pdf`, a `.jpg` scan, and `scanned_lowquality.jpg` ready to upload in order
- [ ] Pre-warm Docker (`docker compose up`) before hitting record — don't record the cold-start wait
- [ ] Know one document ID in advance with a confirmed `review_required: true` question, in case Gemini's output varies between runs
- [ ] Double check your current Gemini API quota isn't exhausted right before recording (check for `429` errors in `docker logs pnbc-worker-1`)
