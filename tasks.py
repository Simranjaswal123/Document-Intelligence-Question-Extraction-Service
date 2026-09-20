import os
import json
import re
import time

from celery import Celery
from google import genai
from google.genai.errors import ServerError, ClientError

from models import SessionLocal, Document, ExtractedQuestion

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=GEMINI_API_KEY)

EXTRACTION_PROMPT = """
Extract all questions from this document. Return ONLY a JSON array where each
item has these fields:
- question_number (string)
- question_text (string)
- options (array of strings, empty array if none)
- answer (string, or null if not present)
- page_numbers (array of integers)
- confidence_score (float between 0.0 and 1.0)

Return valid JSON only, with no extra text or markdown formatting.
"""


def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json", "", 1).strip()
    return json.loads(text)


def normalize_question_number(value):
    digits = re.sub(r"\D", "", value or "")
    return digits or (value or "").strip().lower()


def apply_answer_key(db, answer_key_document):
    answer_questions = (
        db.query(ExtractedQuestion)
        .filter(ExtractedQuestion.document_id == answer_key_document.id)
        .all()
    )
    target_questions = (
        db.query(ExtractedQuestion)
        .filter(ExtractedQuestion.document_id == answer_key_document.related_document_id)
        .all()
    )
    target_by_number = {
        normalize_question_number(q.question_number): q for q in target_questions
    }

    for answer_question in answer_questions:
        target_question = target_by_number.get(
            normalize_question_number(answer_question.question_number)
        )
        if target_question:
            target_question.answer = answer_question.answer

    db.commit()


@celery_app.task(name="process_document_task")
def process_document_task(document_id):
    db = SessionLocal()
    document = None

    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            return

        document.status = "PROCESSING"
        db.commit()

        uploaded_file = client.files.upload(file=document.file_path)

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=[uploaded_file, EXTRACTION_PROMPT],
                )
                break
            except ServerError:
                if attempt == 2:
                    raise
                time.sleep(5)
            except ClientError as e:
                if e.code != 429 or attempt == 2:
                    raise
                time.sleep(5)

        questions = parse_json_response(response.text)

        for item in questions:
            confidence = item.get("confidence_score", 0.0)
            db.add(
                ExtractedQuestion(
                    document_id=document.id,
                    question_number=item.get("question_number"),
                    question_text=item.get("question_text"),
                    options=item.get("options", []),
                    answer=item.get("answer"),
                    source_pages=item.get("page_numbers", []),
                    confidence_score=confidence,
                    review_required=confidence < 0.75,
                )
            )

        db.commit()

        if document.related_document_id and document.doc_type == "ANSWER_KEY":
            apply_answer_key(db, document)

        document.status = "COMPLETED"
        db.commit()

    except Exception:
        if document:
            document.status = "FAILED"
            db.commit()

    finally:
        db.close()
