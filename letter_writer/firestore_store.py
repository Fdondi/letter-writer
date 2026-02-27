from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Iterable, List, Optional
from uuid import uuid4

from google.cloud import firestore

from .config import env_default
from .vector_store import embed, query_vector_similarity


def get_firestore_client() -> firestore.Client:
    """Return a Firestore client using env defaults."""
    project_id = env_default("GOOGLE_CLOUD_PROJECT") or env_default("FIRESTORE_PROJECT_ID")
    database_id = env_default("FIRESTORE_DATABASE")
    # Firestore client will use Application Default Credentials
    # Set GOOGLE_APPLICATION_CREDENTIALS env var or use gcloud auth
    return firestore.Client(project=project_id, database=database_id)


def get_collection():
    """Return the Firestore collection reference."""
    client = get_firestore_client()
    collection_name = env_default("FIRESTORE_COLLECTION", "documents")
    return client.collection(collection_name)


def get_personal_data_collection():
    """Return the Firestore collection reference for personal data.
    
    Uses a flat structure where user_id is the document ID:
    - personal_data/{user_id} contains all user's personal data (CV, settings, etc.)
    """
    client = get_firestore_client()
    return client.collection("personal_data")


def get_personal_data_document(user_id: str):
    """Get the personal data document reference for a specific user.
    
    Document ID = user_id. Document structure:
    {
        "cv_revisions": [{"content": str, "source": str, "created_at": timestamp, ...}, ...],
        "default_languages": [str, ...],
        "style_instructions": str,
        "updated_at": timestamp,
    }
    
    Args:
        user_id: User ID (document ID = user_id)
    
    Returns:
        Firestore document reference: personal_data/{user_id}
    """
    if not user_id:
        raise ValueError("user_id is required for Firestore personal_data operations")
    return get_personal_data_collection().document(str(user_id))


def get_user_data(user_id: str, use_cache: bool = True) -> dict:
    """Get user's personal data (CV, settings, etc.) with optional caching.
    
    This retrieves the entire user document once and can be cached for the request duration.
    Document ID = user_id, so it's a direct lookup without queries.
    
    Args:
        user_id: User ID (document ID = user_id)
        use_cache: If True, cache result for request duration (default: True)
    
    Returns:
        dict with keys: cv_revisions, default_languages, style_instructions, etc.
        Empty dict if document doesn't exist
    
    Raises:
        ValueError: If user_id is not provided
    """
    if not user_id:
        raise ValueError("user_id is required for Firestore personal_data operations")
    
    # Request-scoped cache (thread-local would be better, but simple dict works for single-threaded requests)
    # In production, consider using request-local storage or a proper cache
    cache_key = f"user_data_{user_id}"
    if use_cache and hasattr(get_user_data, "_cache"):
        cache = getattr(get_user_data, "_cache", {})
        if cache_key in cache:
            return cache[cache_key]
    else:
        if not hasattr(get_user_data, "_cache"):
            setattr(get_user_data, "_cache", {})
    
    doc_ref = get_personal_data_document(user_id)
    doc = doc_ref.get()
    
    if not doc.exists:
        user_data = {}
    else:
        user_data = doc.to_dict() or {}
    
    # Cache result for request duration
    if use_cache:
        getattr(get_user_data, "_cache")[cache_key] = user_data
    
    return user_data


def update_user_data_cache(user_id: str, updates: dict) -> None:
    """Merge saved updates into the cached user data so subsequent get_user_data(use_cache=True)
    sees the new values without reading from Firestore. Call this after writing to Firestore.
    """
    if not user_id:
        return
    cache_key = f"user_data_{user_id}"
    if not hasattr(get_user_data, "_cache"):
        setattr(get_user_data, "_cache", {})
    cache = getattr(get_user_data, "_cache", {})
    if cache_key in cache:
        cache[cache_key].update(updates)
    else:
        cache[cache_key] = dict(updates)


def _to_utc_datetime(dt_or_str_or_timestamp):
    """Convert datetime, ISO string, or Firestore Timestamp to timezone-aware UTC datetime.
    
    Firestore automatically converts timezone-aware datetime objects to Timestamps.
    
    Args:
        dt_or_str_or_timestamp: datetime, ISO string, or Firestore Timestamp
    
    Returns:
        timezone-aware UTC datetime object or None if conversion fails
    """
    if dt_or_str_or_timestamp is None:
        return None
    
    # Firestore Timestamp (from reading existing data)
    if hasattr(dt_or_str_or_timestamp, 'timestamp') and hasattr(dt_or_str_or_timestamp, 'seconds'):
        return dt_or_str_or_timestamp.to_datetime() if hasattr(dt_or_str_or_timestamp, 'to_datetime') else datetime.fromtimestamp(dt_or_str_or_timestamp.timestamp(), tz=timezone.utc)
    
    # datetime object - ensure it's timezone-aware UTC
    if isinstance(dt_or_str_or_timestamp, datetime):
        if dt_or_str_or_timestamp.tzinfo is None:
            return dt_or_str_or_timestamp.replace(tzinfo=timezone.utc)
        return dt_or_str_or_timestamp.astimezone(timezone.utc)
    
    # ISO string (from migration or API input)
    if isinstance(dt_or_str_or_timestamp, str):
        try:
            dt_str = dt_or_str_or_timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, AttributeError):
            pass
    
    return None


def _prepare_ai_letters(ai_letters: Optional[List[dict]]) -> List[dict]:
    """Normalize AI/negative letters for storage."""
    now = datetime.now(timezone.utc)
    prepared: List[dict] = []
    for letter in ai_letters or []:
        if not isinstance(letter, dict):
            continue
        created_at = letter.get("created_at") or now
        # Convert to timezone-aware UTC datetime (Firestore will convert to Timestamp automatically)
        if not isinstance(created_at, datetime):
            created_at = _to_utc_datetime(created_at) or now
        elif created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = created_at.astimezone(timezone.utc)
        prepared.append(
            {
                "id": letter.get("id") or str(uuid4()),
                "vendor": letter.get("vendor"),
                "model": letter.get("model"),
                "text": (letter.get("text") or "").strip(),
                "cost": letter.get("cost"),
                "rating": letter.get("rating"),
                "comment": letter.get("comment"),
                "chunks_used": letter.get("chunks_used"),
                "user_corrections": letter.get("user_corrections") or [],  # Git-style edits: [{original, edited}, ...]
                "created_at": created_at,
            }
        )
    return prepared


def serialize_document(doc_dict: dict, doc_id: str) -> dict:
    """Serialize a Firestore document to dict format."""
    if not doc_dict:
        return {}
    result = dict(doc_dict)
    result["id"] = doc_id
    result["ai_letters"] = doc_dict.get("ai_letters") or []
    # Convert Firestore Timestamps to ISO format strings
    # After migration, all dates are stored as Firestore Timestamps
    for ts_field in ("created_at", "updated_at"):
        if ts_field in doc_dict:
            ts = doc_dict[ts_field]
            # Firestore Timestamp - convert to ISO string
            dt = ts.to_datetime() if hasattr(ts, "to_datetime") else datetime.fromtimestamp(ts.timestamp(), tz=timezone.utc)
            result[ts_field] = dt.isoformat()
    return result


def upsert_document(collection, data: dict, *, allow_update: bool = True, user_id: str) -> dict:
    """Insert or update a document. Returns the stored document.
    
    Args:
        collection: Firestore collection reference
        data: Document data dict
        allow_update: If True, update existing document; if False, only insert
        user_id: User ID to scope the document (required for multi-user security)
    
    Raises:
        ValueError: If user_id is not provided
    """
    
    now = datetime.now(timezone.utc)
    company_name_raw = data.get("company_name") or data.get("company")
    # Normalize company_name by stripping whitespace and lowercasing
    company_name = company_name_raw.strip().lower() if company_name_raw else None
    role = data.get("role")
    job_text_normalized = (data.get("job_text") or "").strip()

    # Stable dedupe key for the same application. This lets repeated "create" calls
    # update the same document instead of creating duplicate UUID documents.
    fingerprint_parts = [
        str(user_id or "").strip().lower(),
        str(company_name or "").strip().lower(),
        str(role or "").strip().lower(),
        job_text_normalized,
    ]
    application_fingerprint = hashlib.sha256("\n".join(fingerprint_parts).encode("utf-8")).hexdigest()

    requested_doc_id = data.get("id") or data.get("document_id") or data.get("_id")
    doc_id = requested_doc_id
    dedupe_existing_data = None
    if not doc_id:
        # If caller does a create without ID, reuse an existing equivalent
        # application for this user (even legacy docs without fingerprint).
        for candidate in collection.where("user_id", "==", user_id).stream():
            candidate_data = candidate.to_dict() or {}
            candidate_company = ((candidate_data.get("company_name_original") or candidate_data.get("company_name") or "").strip().lower())
            candidate_role = (candidate_data.get("role") or "").strip().lower()
            candidate_job_text = (candidate_data.get("job_text") or "").strip()
            if (
                candidate_company == str(company_name or "").strip().lower()
                and candidate_role == str(role or "").strip().lower()
                and candidate_job_text == job_text_normalized
            ):
                doc_id = candidate.id
                dedupe_existing_data = candidate_data
                break
        if not doc_id:
            doc_id = str(uuid4())
    
    ai_letters = _prepare_ai_letters(data.get("ai_letters"))
    requirements = data.get("requirements")
    if isinstance(requirements, list):
        requirements_value = requirements
    elif requirements:
        requirements_value = [requirements]
    else:
        requirements_value = []

    doc_ref = collection.document(doc_id)
    
    effective_allow_update = allow_update or (dedupe_existing_data is not None)

    if effective_allow_update:
        existing_doc = doc_ref.get()
        existing_data = dedupe_existing_data or (existing_doc.to_dict() if existing_doc.exists else None)
        
        # Security check: ensure user_id matches on update
        if existing_data and existing_data.get("user_id") != user_id:
            raise PermissionError(f"Document {doc_id} belongs to a different user")
        
        if existing_data:
            # Update existing document
            version = int(existing_data.get("version", 1))
            # Increment version if letter_text or job_text changed
            if (data.get("letter_text", "").strip() != existing_data.get("letter_text", "").strip() or
                data.get("job_text", "").strip() != existing_data.get("job_text", "").strip()):
                version += 1
        else:
            version = 1
    else:
        existing_data = None
        version = 1
    
    # Use timezone-aware UTC datetime - Firestore will automatically convert to Timestamp
    updated_at_dt = now
    
    # Handle created_at
    if not existing_data:
        created_at = data.get("created_at") or now
        created_at_dt = _to_utc_datetime(created_at) or now
    else:
        # Preserve existing created_at, but convert if it's a string
        existing_created_at = existing_data.get("created_at", now)
        created_at_dt = _to_utc_datetime(existing_created_at) or now
    
    base = {
        "user_id": user_id,  # Always store user_id
        "company_name": company_name,
        "company_name_original": data.get("company_name") or data.get("company"),  # Store original for display
        "application_fingerprint": application_fingerprint,
        "role": role,
        "location": data.get("location"),
        "language": data.get("language"),
        "salary": data.get("salary"),
        "requirements": requirements_value,
        "date_applied": data.get("date_applied"),
        "job_text": job_text_normalized,
        "letter_text": (data.get("letter_text") or "").strip(),
        "negative_letter_text": (data.get("negative_letter_text") or "").strip() if data.get("negative_letter_text") else None,
        "blocks": data.get("blocks") or [],
        "ai_letters": ai_letters,
        "notes": data.get("notes"),
        "version": version,
        "updated_at": updated_at_dt,
        "created_at": created_at_dt,
    }
    
    # Store vector if provided (for vector search)
    if "vector" in data:
        base["vector"] = data["vector"]
    
    # Upsert document
    doc_ref.set(base, merge=effective_allow_update)
    
    # Get the stored document
    stored_doc = doc_ref.get()
    stored_dict = stored_doc.to_dict() if stored_doc.exists else {}
    
    return serialize_document(stored_dict, doc_id)


def get_document(collection, doc_id: str, user_id: Optional[str] = None) -> dict | None:
    """Get a document by ID.
    
    Args:
        collection: Firestore collection reference
        doc_id: Document ID
        user_id: User ID to verify ownership (required for security)
    
    Returns:
        Document dict if found and owned by user, None otherwise
    
    Raises:
        ValueError: If user_id is not provided
        PermissionError: If document exists but belongs to a different user
    """
    if not user_id:
        raise ValueError("user_id is required for Firestore document operations")
    
    doc_ref = collection.document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        return None
    
    doc_data = doc.to_dict()
    # Security check: ensure document belongs to the requesting user
    if doc_data.get("user_id") != user_id:
        raise PermissionError(f"Document {doc_id} belongs to a different user")
    
    return serialize_document(doc_data, doc_id)


def list_documents(
    collection,
    *,
    user_id: Optional[str] = None,
    company_name: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> List[dict]:
    """List documents with optional filters.
    
    Args:
        collection: Firestore collection reference
        user_id: User ID to filter documents (required for security)
        company_name: Filter by company name (prefix match)
        role: Filter by role (prefix match)
        limit: Maximum number of documents to return
        skip: Number of documents to skip
    
    Returns:
        List of document dicts belonging to the user
    
    Raises:
        ValueError: If user_id is not provided
    """
    if not user_id:
        raise ValueError("user_id is required for Firestore document operations")
    
    # Always filter by user_id first (required for security)
    query = collection.where("user_id", "==", user_id)
    
    # Track if we need to filter in memory (Firestore doesn't support substring/contains search)
    has_filters = company_name or role
    company_filter_value = None
    role_filter_value = None
    
    # Store filter values for in-memory filtering (case-insensitive substring matching)
    if company_name:
        company_filter_value = company_name.strip()
    if role:
        role_filter_value = role.strip()
    
    # Apply filters in memory (case-insensitive substring matching)
    if has_filters:
        # Fetch all matching documents (filtered by user_id)
        docs = query.stream()
        result = []
        for doc in docs:
            result.append(serialize_document(doc.to_dict(), doc.id))
        
        # Apply company_name filter (case-insensitive contains match)
        if company_filter_value:
            company_lower = company_filter_value.lower()
            result = [d for d in result if company_lower in (d.get("company_name_original") or d.get("company_name") or "").lower()]
        
        # Apply role filter (case-insensitive contains match)
        if role_filter_value:
            role_lower = role_filter_value.lower()
            result = [d for d in result if role_lower in (d.get("role") or "").lower()]
        
        # Sort by created_at descending (most recent first)
        # serialize_document returns ISO strings for dates
        def get_sort_key(doc):
            created_at = doc.get("created_at")
            if not created_at:
                return 0
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, AttributeError):
                return 0
        
        result.sort(key=get_sort_key, reverse=True)
        
        # Apply pagination
        if skip > 0:
            result = result[skip:]
        if len(result) > limit:
            result = result[:limit]
        
        return result
    else:
        # No filters - can use order_by directly
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        
        # Apply pagination
        if skip > 0:
            query = query.offset(skip)
        query = query.limit(limit)
        
        # Execute query
        docs = query.stream()
        result = []
        for doc in docs:
            result.append(serialize_document(doc.to_dict(), doc.id))
        
        return result


def append_negatives(collection, doc_id: str, negatives: List[dict], user_id: Optional[str] = None) -> dict | None:
    """Append negatives to ai_letters array.
    
    Args:
        collection: Firestore collection reference
        doc_id: Document ID
        negatives: List of negative letter dicts to append
        user_id: User ID to verify ownership (required for security)
    
    Returns:
        Updated document dict if found and owned by user, None otherwise
    
    Raises:
        ValueError: If user_id is not provided
        PermissionError: If document belongs to a different user
    """
    if not user_id:
        raise ValueError("user_id is required for Firestore document operations")
    
    if not negatives:
        return get_document(collection, doc_id, user_id=user_id)
    
    now = datetime.now(timezone.utc)
    prepared = _prepare_ai_letters(negatives)
    
    doc_ref = collection.document(doc_id)
    
    # Get current document and append to array
    current_doc = doc_ref.get()
    if not current_doc.exists:
        return None
    
    current_data = current_doc.to_dict()
    # Security check: ensure document belongs to the requesting user
    if current_data.get("user_id") != user_id:
        raise PermissionError(f"Document {doc_id} belongs to a different user")
    
    current_ai_letters = current_data.get("ai_letters", [])
    updated_ai_letters = current_ai_letters + prepared
    
    # Use timezone-aware UTC datetime - Firestore will automatically convert to Timestamp
    updated_at_dt = now
    
    # Update document
    doc_ref.update({
        "ai_letters": updated_ai_letters,
        "updated_at": updated_at_dt,
    })
    
    return get_document(collection, doc_id, user_id=user_id)


def get_companies_collection():
    """Return the Firestore collection reference for companies."""
    client = get_firestore_client()
    return client.collection("companies")


def _normalize_company_doc_id(company_name: str) -> str:
    """Normalize company name into a global company document ID."""
    return company_name.strip().lower().replace(" ", "_")


def _normalize_poc_key(poc_name: str) -> str:
    """Normalize point-of-contact name into a stable nested key."""
    return poc_name.strip().lower().replace(" ", "_")


def save_company_info(company_name: str, data: dict, vector: Optional[List[float]] = None) -> dict:
    """Save company research data.
    
    Args:
        company_name: Company name (used as ID after normalization)
        data: Data to save (reports, etc.)
        vector: Optional vector embedding for fuzzy search
    """
    if not company_name:
        raise ValueError("company_name is required")
    
    # Global company-level cache key (not user-scoped).
    doc_id = _normalize_company_doc_id(company_name)
    
    collection = get_companies_collection()
    
    # Use direct set with merge=True to support arbitrary fields (like reports)
    # upsert_document is too strict and only supports specific document fields
    update_data = {
        "id": doc_id,
        "company_name": company_name,
        "updated_at": datetime.now(timezone.utc),
        **data
    }
    
    # Add vector (provided or generated from company name) for similarity lookup.
    try:
        vec = vector
        if vec is None:
            from openai import OpenAI
            openai_client = OpenAI()
            vec = embed(company_name, openai_client)
        if vec is not None:
            from google.cloud.firestore_v1.vector import Vector
            update_data["vector"] = vec if isinstance(vec, Vector) else Vector(vec)
    except Exception:
        # Vector enrichment is best-effort and should not block company cache writes.
        pass
    
    collection.document(doc_id).set(update_data, merge=True)
    return update_data


def _resolve_company_doc_id(doc_id: str, *, max_hops: int = 3) -> str:
    """Resolve alias redirects in companies collection to canonical document id."""
    collection = get_companies_collection()
    current = doc_id
    hops = 0
    while hops < max_hops:
        snap = collection.document(current).get()
        if not snap.exists:
            return current
        data = snap.to_dict() or {}
        alias_for = data.get("alias_for")
        if not alias_for or alias_for == current:
            return current
        current = str(alias_for)
        hops += 1
    return current


def save_company_alias(alias_company_name: str, canonical_doc_id: str, canonical_company_name: Optional[str] = None) -> dict:
    """Save an alias redirect entry pointing alias -> canonical root company doc.

    Alias documents also store a vector so they can participate in vector search.
    """
    if not alias_company_name or not canonical_doc_id:
        raise ValueError("alias_company_name and canonical_doc_id are required")

    alias_id = _normalize_company_doc_id(alias_company_name)
    canonical_root_id = _resolve_company_doc_id(str(canonical_doc_id))
    if alias_id == canonical_root_id:
        return {"id": alias_id, "alias_for": canonical_root_id}

    collection = get_companies_collection()
    payload = {
        "id": alias_id,
        "company_name": alias_company_name,
        "alias_for": canonical_root_id,
        "canonical_company_name": canonical_company_name or "",
        "updated_at": datetime.now(timezone.utc),
    }

    # Add vector for alias names so vector search can match aliases too.
    try:
        from openai import OpenAI
        openai_client = OpenAI()
        payload["vector"] = embed(alias_company_name, openai_client)
    except Exception:
        pass

    collection.document(alias_id).set(payload, merge=True)
    return payload


def get_company_info(company_name: str) -> Optional[dict]:
    """Get company research data.
    
    Args:
        company_name: Company name
    """
    if not company_name:
        raise ValueError("company_name is required")
        
    requested_id = _normalize_company_doc_id(company_name)
    doc_id = _resolve_company_doc_id(requested_id)
    collection = get_companies_collection()
    doc = collection.document(doc_id).get()
    if doc.exists:
        out = doc.to_dict()
        if requested_id != doc_id and out is not None:
            out = dict(out)
            out["resolved_from_alias"] = requested_id
            out["resolved_to"] = doc_id
        return out
    return None


def save_poc_info(company_name: str, poc_name: str, data: dict) -> dict:
    """Save POC research data into the company document.
    
    Args:
        company_name: Company name (parent document)
        poc_name: POC name
        data: Data to save
    """
    if not company_name or not poc_name:
        raise ValueError("company_name and poc_name are required")
        
    company_id = _normalize_company_doc_id(company_name)
    poc_key = _normalize_poc_key(poc_name)
    
    collection = get_companies_collection()
    
    # Update nested field using dot notation (requires document to exist? No, set with merge handles it)
    # Actually, to update a nested map safely without overwriting other POCs, we need to use
    # a dict with dot notation keys if using update(), or construct the nested dict if using set(merge=True).
    # set(merge=True) merges top-level fields. For nested maps, it merges them too!
    # "If you use set() with merge=True, the contents of the document are updated... Maps are merged."
    
    update_data = {
        "pocs": {
            poc_key: {
                "name": poc_name,
                "updated_at": datetime.now(timezone.utc),
                **data
            }
        },
        # Ensure parent fields exist
        "company_name": company_name,
        "updated_at": datetime.now(timezone.utc)
    }
    
    collection.document(company_id).set(update_data, merge=True)
    return update_data["pocs"][poc_key]


def get_poc_info(company_name: str, poc_name: str) -> Optional[dict]:
    """Get POC research data from company document.
    
    Args:
        company_name: Company name
        poc_name: POC name
    """
    if not company_name or not poc_name:
        raise ValueError("company_name and poc_name are required")
        
    company_id = _resolve_company_doc_id(_normalize_company_doc_id(company_name))
    poc_key = _normalize_poc_key(poc_name)
    
    collection = get_companies_collection()
    doc = collection.document(company_id).get()
    
    if doc.exists:
        data = doc.to_dict()
        pocs = data.get("pocs", {})
        return pocs.get(poc_key)
    return None


def search_similar_companies(company_name: str, *, limit: int = 5) -> List[dict]:
    """Return vector-similar canonical company docs for the input name.

    Alias docs are allowed to match (they have vectors), but returned results are
    flattened to canonical root docs and deduplicated by canonical id.
    """
    if not company_name:
        return []

    collection = get_companies_collection()
    from openai import OpenAI
    openai_client = OpenAI()
    query_vec = embed(company_name, openai_client)

    # Over-fetch a bit so deduplication to canonical ids still yields useful results.
    candidates = query_vector_similarity(collection, query_vec, limit=max(limit * 3, 10))

    out: List[dict] = []
    seen_canonical_ids = set()
    for c in candidates:
        candidate_id = str(c.get("id") or "")
        if not candidate_id:
            continue

        canonical_id = _resolve_company_doc_id(candidate_id)
        if canonical_id in seen_canonical_ids:
            continue

        # If candidate is an alias, return its canonical root doc instead.
        if canonical_id != candidate_id:
            snap = collection.document(canonical_id).get()
            if not snap.exists:
                continue
            canonical = snap.to_dict() or {}
            canonical["id"] = canonical_id
            canonical["matched_via_alias"] = candidate_id
            canonical["matched_alias_name"] = c.get("company_name")
            out.append(canonical)
        else:
            out.append(c)

        seen_canonical_ids.add(canonical_id)
        if len(out) >= limit:
            break

    return out


def documents_by_ids(collection, ids: List[str], user_id: Optional[str] = None) -> List[dict]:
    """Get multiple documents by IDs.
    
    Args:
        collection: Firestore collection reference
        ids: List of document IDs
        user_id: User ID to filter documents (required for security)
    
    Returns:
        List of document dicts belonging to the user
    
    Raises:
        ValueError: If user_id is not provided
    """
    if not user_id:
        raise ValueError("user_id is required for Firestore document operations")
    
    if not ids:
        return []
    
    # Firestore batch get
    doc_refs = [collection.document(doc_id) for doc_id in ids]
    docs = get_firestore_client().get_all(doc_refs)
    
    result = []
    for doc in docs:
        if doc.exists:
            doc_data = doc.to_dict()
            # Security check: only return documents belonging to the requesting user
            if doc_data.get("user_id") == user_id:
                result.append(serialize_document(doc_data, doc.id))
    
    return result
