from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, List, Optional
from uuid import uuid4

from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from .config import env_default


def get_mongo_client(uri: str | None = None) -> MongoClient:
    """Return a Mongo client using env defaults."""
    mongo_uri = uri or env_default("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(mongo_uri, connect=False)


def get_db(client: MongoClient | None = None):
    """Return the Mongo database handle and ensure indexes exist."""
    client = client or get_mongo_client()
    db_name = env_default("MONGO_DB", "letter_writer")
    db = client[db_name]
    ensure_indexes(db)
    return db


def ensure_indexes(db) -> None:
    db.documents.create_index("slug", unique=True, sparse=True)
    db.documents.create_index("company_name")
    db.documents.create_index([("company_name", ASCENDING), ("role", ASCENDING)])


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or str(uuid4())


def build_slug(company_name: str, role: Optional[str], timestamp: Optional[datetime]) -> str:
    """Build a slug: company_role_YYYYMMDD-HHMM (UTC)."""
    ts = timestamp or datetime.utcnow()
    parts = [company_name]
    if role:
        parts.append(role)
    parts.append(ts.strftime("%Y%m%d-%H%M"))
    return _slugify("-".join(parts))


def _prepare_ai_letters(ai_letters: Optional[List[dict]]) -> List[dict]:
    """Normalize AI/negative letters for storage."""
    now = datetime.utcnow()
    prepared: List[dict] = []
    for letter in ai_letters or []:
        if not isinstance(letter, dict):
            continue
        prepared.append(
            {
                "id": letter.get("id") or str(uuid4()),
                "vendor": letter.get("vendor"),
                "model": letter.get("model"),
                "text": (letter.get("text") or "").strip(),
                "cost": letter.get("cost"),
                "created_at": letter.get("created_at") or now,
            }
        )
    return prepared


def serialize_document(doc: dict) -> dict:
    if not doc:
        return {}
    result = {k: v for k, v in doc.items() if k != "_id"}
    result["id"] = str(doc.get("_id"))
    result["ai_letters"] = doc.get("ai_letters") or []
    for ts_field in ("created_at", "updated_at"):
        if ts_field in doc and hasattr(doc[ts_field], "isoformat"):
            result[ts_field] = doc[ts_field].isoformat()
    return result


def upsert_document(db, data: dict, *, allow_update: bool = True) -> dict:
    """Insert or update a document. Returns the stored document."""
    now = datetime.utcnow()
    doc_id = data.get("id") or data.get("document_id") or data.get("_id") or str(uuid4())
    company_name = data.get("company_name") or data.get("company")
    role = data.get("role")
    ts_for_slug = data.get("timestamp") or data.get("created_at") or now
    slug = data.get("slug") or (build_slug(company_name, role, ts_for_slug) if company_name else None)

    ai_letters = _prepare_ai_letters(data.get("ai_letters"))

    base = {
        "_id": doc_id,
        "slug": slug,
        "company_name": company_name,
        "role": role,
        "location": data.get("location"),
        "date_applied": data.get("date_applied"),
        "status": data.get("status"),
        "vendor": data.get("vendor"),
        "model": data.get("model"),
        "job_text": (data.get("job_text") or "").strip(),
        "letter_text": (data.get("letter_text") or "").strip(),
        "negative_letter_text": (data.get("negative_letter_text") or "").strip() if data.get("negative_letter_text") else None,
        "blocks": data.get("blocks") or [],
        "ai_letters": ai_letters,
        "tags": data.get("tags") or [],
        "notes": data.get("notes"),
        "version": int(data.get("version") or 1),
        "created_at": data.get("created_at") or now,
        "updated_at": now,
    }

    existing = db.documents.find_one({"_id": doc_id}) if allow_update else None
    if existing and allow_update:
        base["version"] = int(existing.get("version", 1)) + 1 if (
            base["letter_text"] != existing.get("letter_text")
            or base["job_text"] != existing.get("job_text")
        ) else existing.get("version", 1)
        db.documents.update_one({"_id": doc_id}, {"$set": base})
        stored = db.documents.find_one({"_id": doc_id})
    else:
        # Try insert; on duplicate slug, append a short suffix and retry.
        attempts = 0
        while True:
            try:
                db.documents.insert_one(base)
                stored = base
                break
            except DuplicateKeyError:
                attempts += 1
                base["slug"] = f"{base.get('slug')}-{uuid4().hex[:6]}"
                if attempts > 3:
                    raise

    return serialize_document(stored)


def get_document(db, doc_id: str) -> dict | None:
    doc = db.documents.find_one({"_id": doc_id})
    return serialize_document(doc) if doc else None


def list_documents(
    db,
    *,
    company_name: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    limit: int = 50,
    skip: int = 0,
) -> List[dict]:
    query: dict = {}
    if company_name:
        query["company_name"] = {"$regex": company_name, "$options": "i"}
    if role:
        query["role"] = {"$regex": role, "$options": "i"}
    if status:
        query["status"] = status
    if vendor:
        query["vendor"] = vendor
    if model:
        query["model"] = model
    if tags:
        query["tags"] = {"$all": list(tags)}

    cursor = (
        db.documents.find(query)
        .sort("updated_at", -1)
        .skip(skip)
        .limit(limit)
    )
    return [serialize_document(doc) for doc in cursor]


def append_negatives(db, doc_id: str, negatives: List[dict]) -> dict | None:
    """Backwards-compatible API: append provided negatives into ai_letters."""
    if not negatives:
        return get_document(db, doc_id)
    now = datetime.utcnow()
    prepared = _prepare_ai_letters(negatives)
    db.documents.update_one(
        {"_id": doc_id},
        {"$push": {"ai_letters": {"$each": prepared}}, "$set": {"updated_at": now}},
    )
    return get_document(db, doc_id)


def documents_by_ids(db, ids: List[str]) -> List[dict]:
    if not ids:
        return []
    cursor = db.documents.find({"_id": {"$in": ids}})
    return [serialize_document(doc) for doc in cursor]

