import os
import uuid
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    JSON,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@db:5432/docprocessing"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    doc_type = Column(String, default="QUESTION_PAPER")
    status = Column(String, default="PENDING")
    related_document_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExtractedQuestion(Base):
    __tablename__ = "extracted_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    question_number = Column(String)
    question_text = Column(Text)
    options = Column(JSON)
    answer = Column(String, nullable=True)
    source_pages = Column(JSON)
    confidence_score = Column(Float)
    review_required = Column(Boolean)
    warning_message = Column(String, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
