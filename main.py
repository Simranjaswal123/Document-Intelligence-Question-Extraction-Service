import os
import shutil
import uuid

from fastapi import APIRouter, FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from models import SessionLocal, Document, ExtractedQuestion, init_db
from tasks import process_document_task

app = FastAPI(title="Document Processing & Question Extraction API")
api_router = APIRouter(prefix="/api/v1")

UPLOAD_DIR = "/uploads"
API_KEY = os.getenv("API_KEY", "changeme")


class LinkRequest(BaseModel):
    question_doc_id: str
    answer_doc_id: str


def verify_api_key(x_api_key):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def question_to_dict(question):
    return {
        "id": question.id,
        "document_id": question.document_id,
        "question_number": question.question_number,
        "question_text": question.question_text,
        "options": question.options,
        "answer": question.answer,
        "source_pages": question.source_pages,
        "confidence_score": question.confidence_score,
        "review_required": question.review_required,
        "warning_message": question.warning_message,
    }


@app.on_event("startup")
def on_startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()


@api_router.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("QUESTION_PAPER"),
    x_api_key: str = Header(None),
):
    verify_api_key(x_api_key)

    doc_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{file.filename}")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    db = SessionLocal()
    doc = Document(id=doc_id, filename=file.filename, file_path=file_path, doc_type=doc_type, status="PENDING")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    document_id = doc.id
    status = doc.status
    db.close()

    process_document_task.delay(document_id)

    return {"document_id": document_id, "status": status}


@api_router.get("/documents/{id}/status")
def get_document_status(id: str, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)

    db = SessionLocal()
    doc = db.query(Document).filter(Document.id == id).first()
    db.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"document_id": doc.id, "status": doc.status}


@api_router.get("/documents/{id}/questions")
def get_document_questions(id: str, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)

    db = SessionLocal()
    questions = db.query(ExtractedQuestion).filter(ExtractedQuestion.document_id == id).all()
    db.close()

    return [question_to_dict(q) for q in questions]


@api_router.get("/questions/{id}")
def get_question(id: int, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)

    db = SessionLocal()
    question = db.query(ExtractedQuestion).filter(ExtractedQuestion.id == id).first()
    db.close()

    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    return question_to_dict(question)


@api_router.get("/documents/{id}/review-items")
def get_review_items(id: str, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)

    db = SessionLocal()
    questions = (
        db.query(ExtractedQuestion)
        .filter(ExtractedQuestion.document_id == id, ExtractedQuestion.review_required == True)
        .all()
    )
    db.close()

    return [question_to_dict(q) for q in questions]


@api_router.get("/documents/{id}/answers")
def get_document_answers(id: str, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)

    db = SessionLocal()
    questions = db.query(ExtractedQuestion).filter(ExtractedQuestion.document_id == id).all()
    db.close()

    return [{"question_number": q.question_number, "answer": q.answer} for q in questions]


@api_router.post("/documents/link")
def link_documents(body: LinkRequest, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)

    db = SessionLocal()
    question_doc = db.query(Document).filter(Document.id == body.question_doc_id).first()
    answer_doc = db.query(Document).filter(Document.id == body.answer_doc_id).first()

    if not question_doc or not answer_doc:
        db.close()
        raise HTTPException(status_code=404, detail="One or both documents not found")

    answer_doc.doc_type = "ANSWER_KEY"
    answer_doc.related_document_id = question_doc.id
    db.commit()
    answer_doc_id = answer_doc.id
    db.close()

    process_document_task.delay(answer_doc_id)

    return {"question_doc_id": body.question_doc_id, "answer_doc_id": body.answer_doc_id, "status": "linked"}


app.include_router(api_router)


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return INDEX_HTML


INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Document Question Extractor</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { font-family: 'Segoe UI', ui-sans-serif, system-ui, sans-serif; }
  .dropzone.dragover { border-color: #6366f1; background-color: #eef2ff; }
  .spinner {
    border: 3px solid #e5e7eb;
    border-top-color: #6366f1;
    border-radius: 50%;
    width: 18px;
    height: 18px;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">

<header class="bg-white border-b border-slate-200">
  <div class="max-w-5xl mx-auto px-4 py-4 flex flex-wrap items-center justify-between gap-3">
    <div>
      <h1 class="text-xl font-bold text-slate-900">Document Question Extractor</h1>
      <p class="text-sm text-slate-500">Upload a question paper or answer key and extract structured questions</p>
    </div>
    <div class="flex items-center gap-2">
      <input id="apiKeyInput" type="text" placeholder="X-API-KEY"
        class="border border-slate-300 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
      <button id="openLinkModalBtn"
        class="bg-slate-900 hover:bg-slate-700 text-white text-sm font-medium px-3 py-1.5 rounded-lg">
        Link Documents
      </button>
    </div>
  </div>
</header>

<main class="max-w-5xl mx-auto px-4 py-8">

  <div class="flex gap-2 mb-6">
    <button id="tabUploadBtn" class="tab-btn px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 text-white">
      Upload &amp; Process
    </button>
    <button id="tabReviewBtn" class="tab-btn px-4 py-2 rounded-lg text-sm font-semibold bg-white text-slate-600 border border-slate-200">
      Review Required Items
    </button>
  </div>

  <section id="uploadPanel">
    <div class="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
      <div id="dropzone" class="dropzone border-2 border-dashed border-slate-300 rounded-xl py-12 text-center cursor-pointer transition-colors">
        <p class="text-slate-500">
          <span class="font-semibold text-indigo-600">Click to browse</span> or drag &amp; drop a PDF / image here
        </p>
        <p id="selectedFileName" class="text-sm text-slate-400 mt-2"></p>
        <input id="fileInput" type="file" accept="application/pdf,image/*,text/plain,.txt" class="hidden" />
      </div>

      <div class="flex flex-wrap items-end gap-4 mt-5">
        <div>
          <label class="block text-xs font-medium text-slate-500 mb-1">Document Type</label>
          <select id="docTypeSelect" class="border border-slate-300 rounded-lg px-3 py-2 text-sm">
            <option value="QUESTION_PAPER">QUESTION_PAPER</option>
            <option value="ANSWER_KEY">ANSWER_KEY</option>
          </select>
        </div>
        <button id="uploadBtn"
          class="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-5 py-2 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed">
          Upload &amp; Process
        </button>
      </div>

      <div id="statusArea" class="hidden mt-6 border-t border-slate-100 pt-5">
        <div class="flex items-center gap-3 flex-wrap">
          <span id="statusSpinner" class="spinner hidden"></span>
          <span id="statusPill" class="text-sm font-semibold px-3 py-1 rounded-full bg-slate-100 text-slate-600">PENDING</span>
          <span id="statusDocId" class="text-xs text-slate-400 font-mono"></span>
          <button id="copyStatusIdBtn" class="text-xs font-medium text-indigo-600 hover:underline">Copy ID</button>
        </div>
        <p id="statusMessage" class="text-sm text-slate-500 mt-2"></p>
      </div>
    </div>

    <div class="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
      <h2 class="text-sm font-semibold text-slate-700 mb-1">Recent Uploads</h2>
      <p class="text-xs text-slate-400 mb-3">Document IDs from your last few uploads — copy one to use in Review Items or Link Documents.</p>
      <div id="recentUploadsList" class="divide-y divide-slate-100">
        <p id="recentUploadsEmpty" class="text-sm text-slate-400 py-2">No uploads yet.</p>
      </div>
    </div>

    <div id="questionsGrid" class="grid gap-4"></div>
  </section>

  <section id="reviewPanel" class="hidden">
    <div class="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 mb-6">
      <label class="block text-xs font-medium text-slate-500 mb-1">Document ID</label>
      <div class="flex gap-2">
        <input id="reviewDocIdInput" type="text" placeholder="Paste a document ID"
          class="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono" />
        <button id="loadReviewBtn" class="bg-slate-900 hover:bg-slate-700 text-white font-semibold px-4 py-2 rounded-lg">
          Load
        </button>
      </div>
    </div>
    <div id="reviewGrid" class="grid gap-4"></div>
    <p id="reviewEmptyMsg" class="text-sm text-slate-400 hidden">No low-confidence items found for this document.</p>
  </section>

</main>

<div id="linkModalBackdrop" class="hidden fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
  <div class="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
    <h2 class="text-lg font-bold text-slate-900 mb-1">Link Question Paper &amp; Answer Key</h2>
    <p class="text-sm text-slate-500 mb-4">Linking triggers answer matching for the answer key document.</p>

    <label class="block text-xs font-medium text-slate-500 mb-1">Question Paper Document ID</label>
    <input id="questionDocIdInput" type="text" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono mb-3" />

    <label class="block text-xs font-medium text-slate-500 mb-1">Answer Key Document ID</label>
    <input id="answerDocIdInput" type="text" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono mb-4" />

    <p id="linkMessage" class="text-sm mb-3 hidden"></p>

    <div class="flex justify-end gap-2">
      <button id="closeLinkModalBtn" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-600 hover:bg-slate-100">Cancel</button>
      <button id="submitLinkBtn" class="px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-700 text-white">Link</button>
    </div>
  </div>
</div>

<script>
const API_BASE = "/api/v1";
let selectedFile = null;
let currentDocumentId = null;
let pollTimer = null;
let pollAttempts = 0;
const MAX_POLL_ATTEMPTS = 90;

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getApiKey() {
  return document.getElementById("apiKeyInput").value.trim();
}

async function apiFetch(path, options = {}) {
  const headers = Object.assign({ "X-API-KEY": getApiKey() }, options.headers || {});
  const response = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (e) {}
    throw new Error(detail);
  }
  return response.json();
}

// ---- API key persistence ----
const apiKeyInput = document.getElementById("apiKeyInput");
apiKeyInput.value = localStorage.getItem("docapp_api_key") || "changeme";
apiKeyInput.addEventListener("input", () => {
  localStorage.setItem("docapp_api_key", apiKeyInput.value.trim());
});

// ---- Tabs ----
const tabUploadBtn = document.getElementById("tabUploadBtn");
const tabReviewBtn = document.getElementById("tabReviewBtn");
const uploadPanel = document.getElementById("uploadPanel");
const reviewPanel = document.getElementById("reviewPanel");

function activateTab(tab) {
  const isUpload = tab === "upload";
  uploadPanel.classList.toggle("hidden", !isUpload);
  reviewPanel.classList.toggle("hidden", isUpload);
  tabUploadBtn.className = "tab-btn px-4 py-2 rounded-lg text-sm font-semibold " + (isUpload ? "bg-indigo-600 text-white" : "bg-white text-slate-600 border border-slate-200");
  tabReviewBtn.className = "tab-btn px-4 py-2 rounded-lg text-sm font-semibold " + (!isUpload ? "bg-indigo-600 text-white" : "bg-white text-slate-600 border border-slate-200");
}
tabUploadBtn.addEventListener("click", () => activateTab("upload"));
tabReviewBtn.addEventListener("click", () => {
  activateTab("review");
  if (currentDocumentId) {
    document.getElementById("reviewDocIdInput").value = currentDocumentId;
  }
});

// ---- Recent uploads ----
const recentUploadsList = document.getElementById("recentUploadsList");

function loadRecentUploads() {
  try {
    return JSON.parse(localStorage.getItem("docapp_recent_uploads") || "[]");
  } catch (e) {
    return [];
  }
}

function saveRecentUpload(entry) {
  const uploads = loadRecentUploads();
  uploads.unshift(entry);
  localStorage.setItem("docapp_recent_uploads", JSON.stringify(uploads.slice(0, 8)));
  renderRecentUploads();
}

function renderRecentUploads() {
  const uploads = loadRecentUploads();
  if (!uploads.length) {
    recentUploadsList.innerHTML = '<p class="text-sm text-slate-400 py-2">No uploads yet.</p>';
    return;
  }
  recentUploadsList.innerHTML = uploads.map(u =>
    '<div class="flex flex-wrap items-center justify-between gap-2 py-2">' +
      '<div class="min-w-0">' +
        '<p class="text-sm font-medium text-slate-800 truncate">' + escapeHtml(u.filename) + '</p>' +
        '<p class="text-xs text-slate-400 font-mono truncate">' + escapeHtml(u.id) + '</p>' +
      '</div>' +
      '<div class="flex items-center gap-2 shrink-0">' +
        '<span class="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-500">' + escapeHtml(u.doc_type) + '</span>' +
        '<button class="copy-upload-id text-xs font-medium text-indigo-600 hover:underline" data-id="' + escapeHtml(u.id) + '">Copy</button>' +
        '<button class="use-in-link text-xs font-medium text-slate-600 hover:underline" data-id="' + escapeHtml(u.id) + '">Link...</button>' +
      '</div>' +
    '</div>'
  ).join("");
}

recentUploadsList.addEventListener("click", (e) => {
  const copyBtn = e.target.closest(".copy-upload-id");
  if (copyBtn) {
    navigator.clipboard.writeText(copyBtn.dataset.id);
    copyBtn.textContent = "Copied!";
    setTimeout(() => { copyBtn.textContent = "Copy"; }, 1200);
    return;
  }
  const linkBtn = e.target.closest(".use-in-link");
  if (linkBtn) {
    openLinkModal();
    const questionInput = document.getElementById("questionDocIdInput");
    const answerInput = document.getElementById("answerDocIdInput");
    if (!questionInput.value) {
      questionInput.value = linkBtn.dataset.id;
    } else {
      answerInput.value = linkBtn.dataset.id;
    }
  }
});

renderRecentUploads();

// ---- Drag & drop upload ----
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const selectedFileName = document.getElementById("selectedFileName");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) {
    selectedFile = e.dataTransfer.files[0];
    selectedFileName.textContent = "Selected: " + selectedFile.name;
  }
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) {
    selectedFile = fileInput.files[0];
    selectedFileName.textContent = "Selected: " + selectedFile.name;
  }
});

// ---- Confidence badge ----
function confidenceBadge(question) {
  const flagged = question.review_required || question.confidence_score < 0.75;
  const pct = Math.round((question.confidence_score || 0) * 100);
  const classes = flagged
    ? "bg-red-100 text-red-700"
    : "bg-emerald-100 text-emerald-700";
  return '<span class="text-xs font-bold px-2 py-1 rounded-full ' + classes + '">' + pct + '% confidence</span>';
}

// ---- Question card renderer ----
function renderQuestionCard(q) {
  const flagged = q.review_required || q.confidence_score < 0.75;
  const options = Array.isArray(q.options) ? q.options : [];
  const pages = Array.isArray(q.source_pages) ? q.source_pages : [];

  const optionsHtml = options.length
    ? '<ul class="mt-2 space-y-1 text-sm text-slate-600">' +
        options.map(opt => '<li class="pl-3 border-l-2 border-slate-200">' + escapeHtml(opt) + '</li>').join("") +
      '</ul>'
    : '<p class="text-sm text-slate-400 italic mt-2">No options extracted</p>';

  const answerHtml = q.answer
    ? '<span class="text-xs font-semibold px-2 py-1 rounded-full bg-indigo-100 text-indigo-700">Answer: ' + escapeHtml(q.answer) + '</span>'
    : '<span class="text-xs font-medium px-2 py-1 rounded-full bg-slate-100 text-slate-400">Answer not resolved</span>';

  const pagesHtml = pages.map(p => '<span class="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-500">Page ' + escapeHtml(p) + '</span>').join(" ");

  const warningHtml = q.warning_message
    ? '<p class="text-xs text-red-600 mt-2">⚠ ' + escapeHtml(q.warning_message) + '</p>'
    : "";

  return (
    '<div class="bg-white rounded-2xl border ' + (flagged ? "border-red-200" : "border-slate-200") + ' shadow-sm p-5">' +
      '<div class="flex items-start justify-between gap-3">' +
        '<h3 class="font-semibold text-slate-900">Q' + escapeHtml(q.question_number) + '. ' + escapeHtml(q.question_text) + '</h3>' +
        confidenceBadge(q) +
      '</div>' +
      optionsHtml +
      '<div class="flex flex-wrap items-center gap-2 mt-3">' + answerHtml + pagesHtml + '</div>' +
      warningHtml +
    '</div>'
  );
}

// ---- Status polling ----
const statusArea = document.getElementById("statusArea");
const statusPill = document.getElementById("statusPill");
const statusSpinner = document.getElementById("statusSpinner");
const statusDocId = document.getElementById("statusDocId");
const statusMessage = document.getElementById("statusMessage");
const questionsGrid = document.getElementById("questionsGrid");

document.getElementById("copyStatusIdBtn").addEventListener("click", (e) => {
  if (!currentDocumentId) return;
  navigator.clipboard.writeText(currentDocumentId);
  e.target.textContent = "Copied!";
  setTimeout(() => { e.target.textContent = "Copy ID"; }, 1200);
});

function setStatusPill(status) {
  const map = {
    PENDING: "bg-slate-100 text-slate-600",
    PROCESSING: "bg-amber-100 text-amber-700",
    COMPLETED: "bg-emerald-100 text-emerald-700",
    FAILED: "bg-red-100 text-red-700",
  };
  statusPill.className = "text-sm font-semibold px-3 py-1 rounded-full " + (map[status] || map.PENDING);
  statusPill.textContent = status;
}

async function pollStatus(documentId) {
  pollAttempts += 1;
  try {
    const data = await apiFetch("/documents/" + documentId + "/status");
    setStatusPill(data.status);

    if (data.status === "COMPLETED") {
      clearInterval(pollTimer);
      statusSpinner.classList.add("hidden");
      statusMessage.textContent = "Extraction complete.";
      await loadQuestions(documentId);
      return;
    }
    if (data.status === "FAILED") {
      clearInterval(pollTimer);
      statusSpinner.classList.add("hidden");
      statusMessage.textContent = "Processing failed for this document.";
      return;
    }
    if (pollAttempts >= MAX_POLL_ATTEMPTS) {
      clearInterval(pollTimer);
      statusSpinner.classList.add("hidden");
      statusMessage.textContent = "Still processing — taking longer than expected. Check back later.";
    }
  } catch (err) {
    clearInterval(pollTimer);
    statusSpinner.classList.add("hidden");
    statusMessage.textContent = "Error checking status: " + err.message;
  }
}

async function loadQuestions(documentId) {
  try {
    const questions = await apiFetch("/documents/" + documentId + "/questions");
    questionsGrid.innerHTML = questions.map(renderQuestionCard).join("");
  } catch (err) {
    questionsGrid.innerHTML = '<p class="text-sm text-red-600">Failed to load questions: ' + escapeHtml(err.message) + '</p>';
  }
}

// ---- Upload button ----
document.getElementById("uploadBtn").addEventListener("click", async () => {
  if (!selectedFile) {
    alert("Please select a file first.");
    return;
  }
  const uploadBtn = document.getElementById("uploadBtn");
  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading...";

  questionsGrid.innerHTML = "";
  statusArea.classList.remove("hidden");
  statusMessage.textContent = "";
  statusSpinner.classList.remove("hidden");
  setStatusPill("PENDING");

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("doc_type", document.getElementById("docTypeSelect").value);

  try {
    const response = await fetch(API_BASE + "/upload", {
      method: "POST",
      headers: { "X-API-KEY": getApiKey() },
      body: formData,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || response.statusText);
    }
    const data = await response.json();
    currentDocumentId = data.document_id;
    statusDocId.textContent = "Document ID: " + currentDocumentId;
    setStatusPill(data.status);
    saveRecentUpload({
      id: currentDocumentId,
      filename: selectedFile.name,
      doc_type: document.getElementById("docTypeSelect").value,
    });

    pollAttempts = 0;
    clearInterval(pollTimer);
    pollTimer = setInterval(() => pollStatus(currentDocumentId), 2000);
  } catch (err) {
    statusSpinner.classList.add("hidden");
    statusMessage.textContent = "Upload failed: " + err.message;
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Upload & Process";
  }
});

// ---- Review items ----
document.getElementById("loadReviewBtn").addEventListener("click", async () => {
  const docId = document.getElementById("reviewDocIdInput").value.trim();
  const reviewGrid = document.getElementById("reviewGrid");
  const reviewEmptyMsg = document.getElementById("reviewEmptyMsg");
  reviewEmptyMsg.classList.add("hidden");
  reviewGrid.innerHTML = "";

  if (!docId) {
    alert("Please enter a document ID.");
    return;
  }

  try {
    const items = await apiFetch("/documents/" + docId + "/review-items");
    if (!items.length) {
      reviewEmptyMsg.classList.remove("hidden");
    } else {
      reviewGrid.innerHTML = items.map(renderQuestionCard).join("");
    }
  } catch (err) {
    reviewGrid.innerHTML = '<p class="text-sm text-red-600">Failed to load review items: ' + escapeHtml(err.message) + '</p>';
  }
});

// ---- Link modal ----
const linkModalBackdrop = document.getElementById("linkModalBackdrop");
const linkMessage = document.getElementById("linkMessage");

function openLinkModal() {
  linkMessage.classList.add("hidden");
  linkModalBackdrop.classList.remove("hidden");
}

document.getElementById("openLinkModalBtn").addEventListener("click", () => {
  document.getElementById("questionDocIdInput").value = "";
  document.getElementById("answerDocIdInput").value = "";
  openLinkModal();
});
document.getElementById("closeLinkModalBtn").addEventListener("click", () => {
  linkModalBackdrop.classList.add("hidden");
});
document.getElementById("submitLinkBtn").addEventListener("click", async () => {
  const questionDocId = document.getElementById("questionDocIdInput").value.trim();
  const answerDocId = document.getElementById("answerDocIdInput").value.trim();

  if (!questionDocId || !answerDocId) {
    linkMessage.className = "text-sm mb-3 text-red-600";
    linkMessage.textContent = "Both document IDs are required.";
    linkMessage.classList.remove("hidden");
    return;
  }

  try {
    await apiFetch("/documents/link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question_doc_id: questionDocId, answer_doc_id: answerDocId }),
    });
    linkMessage.className = "text-sm mb-3 text-emerald-600";
    linkMessage.textContent = "Linked successfully. Answer matching has been triggered.";
    linkMessage.classList.remove("hidden");
    setTimeout(() => linkModalBackdrop.classList.add("hidden"), 1500);
  } catch (err) {
    linkMessage.className = "text-sm mb-3 text-red-600";
    linkMessage.textContent = "Failed to link: " + err.message;
    linkMessage.classList.remove("hidden");
  }
});
</script>

</body>
</html>
"""
