"""
Cost tracking module using Redis for fast atomic operations.

Falls back to in-memory tracking if Redis is unavailable.

Costs are tracked in Redis (or memory) during operation, then batch-inserted to BigQuery:
- On letter completion
- Every 30 minutes (configurable)
- On server shutdown

BigQuery table is partitioned by month and clustered by user_id for efficient queries.
Running totals are read from a materialized view or query.
"""

import atexit
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Redis connection (lazy-loaded)
_redis_client = None
_redis_lock = threading.Lock()
_redis_available = None  # None = not checked yet, True/False = checked

# BigQuery client (lazy-loaded)
_bigquery_client = None
_bigquery_lock = threading.Lock()

# In-memory fallback storage (thread-safe)
_memory_lock = threading.Lock()
_memory_store = {
    "total": 0.0,
    "services": {},  # service_name -> {"total": float, "count": int}
    "users": {},     # user_id -> {"total": float, "services": {service_name -> {"total": float, "count": int}}}
    "requests": [],  # List of individual requests for BigQuery insert
}

# Periodic flush thread
_flush_thread: Optional[threading.Thread] = None
_flush_stop_event = threading.Event()
_flush_started = False

# Redis key prefixes
REDIS_PREFIX = "costs:"
TOTAL_KEY = f"{REDIS_PREFIX}total"
SERVICE_PREFIX = f"{REDIS_PREFIX}service:"
USER_PREFIX = f"{REDIS_PREFIX}user:"

# Flush interval in seconds (default: 30 minutes)
FLUSH_INTERVAL = int(os.environ.get("COST_FLUSH_INTERVAL_SECONDS", 1800))

# BigQuery configuration
BIGQUERY_PROJECT = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", "letter_writer")
BIGQUERY_TABLE = os.environ.get("BIGQUERY_TABLE", "api_costs")

# Mapping from JSON filename (stem) to vendor display name for model pricing API
_CLIENT_JSON_VENDORS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google",
    "mistral": "Mistral",
    "grok": "xAI",
    "deepseeek": "DeepSeek",
}


def _parse_price_field(val: Any) -> float:
    """Extract a single price (per 1M tokens) from JSON. Handles Gemini tiered format."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        # Use "low" tier for projection (typical for smaller contexts)
        return float(val.get("low", val.get("high", 0.0)) or 0.0)
    return 0.0


def get_all_model_pricing() -> Dict[str, List[Dict[str, Any]]]:
    """Load model pricing from all client JSON files.

    Returns:
        Dict mapping vendor display name -> list of {"id", "name", "input", "output"}
        where input/output are per-1M-token prices in USD.
    """
    clients_dir = Path(__file__).resolve().parent / "clients"
    if not clients_dir.exists():
        return {}

    result: Dict[str, List[Dict[str, Any]]] = {}
    for json_path in sorted(clients_dir.glob("*.json")):
        vendor_key = json_path.stem
        vendor_label = _CLIENT_JSON_VENDORS.get(vendor_key, vendor_key.replace("_", " ").title())
        try:
            cfg = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load %s: %s", json_path, e)
            continue
        models_cfg = cfg.get("models", {})
        if not isinstance(models_cfg, dict):
            continue
        models = []
        for model_id, model_cfg in models_cfg.items():
            if not isinstance(model_cfg, dict):
                continue
            input_price = _parse_price_field(model_cfg.get("input", 0.0))
            output_price = _parse_price_field(model_cfg.get("output", 0.0))
            if input_price == 0 and output_price == 0:
                continue
            # Humanize model id for display: "claude-haiku-4-5" -> "Claude Haiku 4-5"
            name = model_id.replace("-", " ").title()
            models.append({
                "id": model_id,
                "name": name,
                "input": round(input_price, 2),
                "output": round(output_price, 2),
            })
        if models:
            result[vendor_label] = models

    return result


def _get_redis_client():
    """Get or create Redis client (lazy initialization).
    
    Returns None if Redis is unavailable (will use in-memory fallback).
    """
    global _redis_client, _redis_available
    
    if _redis_available is False:
        return None  # Already checked, Redis not available
    
    if _redis_client is not None:
        return _redis_client
    
    with _redis_lock:
        if _redis_available is False:
            return None
        if _redis_client is not None:
            return _redis_client
        
        try:
            import redis
            
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            _redis_client = redis.from_url(redis_url, decode_responses=True)
            
            # Test connection
            _redis_client.ping()
            _redis_available = True
            logger.info(f"Connected to Redis at {redis_url}")
            
            return _redis_client
            
        except ImportError:
            logger.info("Redis not installed. Using in-memory cost tracking.")
            _redis_available = False
            return None
        except Exception as e:
            logger.info(f"Redis not available ({e}). Using in-memory cost tracking.")
            _redis_available = False
            return None


def _get_bigquery_client():
    """Get or create BigQuery client (lazy initialization)."""
    global _bigquery_client
    
    if _bigquery_client is not None:
        return _bigquery_client
    
    # Skip if no project configured
    if not BIGQUERY_PROJECT:
        return None
    
    with _bigquery_lock:
        if _bigquery_client is not None:
            return _bigquery_client
        
        # Re-check inside lock
        if not BIGQUERY_PROJECT:
            return None
        
        try:
            from google.cloud import bigquery
            
            _bigquery_client = bigquery.Client(project=BIGQUERY_PROJECT)
            logger.info(f"Connected to BigQuery project: {BIGQUERY_PROJECT}")
            return _bigquery_client
            
        except ImportError:
            logger.warning("google-cloud-bigquery not installed. BigQuery flush disabled.")
            return None
        except Exception as e:
            logger.warning(f"BigQuery not available: {e}")
            return None


def _ensure_bigquery_table():
    """Ensure the BigQuery table exists with proper schema and partitioning.
    
    Schema is defined in bigquery_schema.py for version control.
    """
    client = _get_bigquery_client()
    if client is None:
        return False
    
    try:
        from google.cloud import bigquery
        from .bigquery_schema import get_bigquery_schema, TABLE_CONFIG
        
        table_id = f"{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}"
        
        # Check if table exists
        try:
            client.get_table(table_id)
            return True
        except Exception:
            pass  # Table doesn't exist, create it
        
        # Create dataset if needed
        dataset_id = f"{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}"
        try:
            client.get_dataset(dataset_id)
        except Exception:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = os.environ.get("BIGQUERY_LOCATION", "EU")
            client.create_dataset(dataset, exists_ok=True)
            logger.info(f"Created BigQuery dataset: {dataset_id} in location {dataset.location}")
        
        # Create table with schema from bigquery_schema.py
        schema = get_bigquery_schema()
        table = bigquery.Table(table_id, schema=schema)
        table.description = TABLE_CONFIG["description"]
        
        # Partition by month (using timestamp field)
        partition_type = getattr(
            bigquery.TimePartitioningType,
            TABLE_CONFIG["partitioning"]["type"]
        )
        table.time_partitioning = bigquery.TimePartitioning(
            type_=partition_type,
            field=TABLE_CONFIG["partitioning"]["field"],
        )
        
        # Cluster by user_id, service for efficient queries
        table.clustering_fields = TABLE_CONFIG["clustering"]
        
        client.create_table(table)
        logger.info(f"Created BigQuery table: {table_id} (partitioned by month, clustered by {', '.join(TABLE_CONFIG['clustering'])})")
        
        return True
        
    except Exception as e:
        logger.error(f"Error ensuring BigQuery table: {e}")
        return False


def _ensure_flush_thread():
    """Ensure the periodic flush thread is running."""
    global _flush_thread, _flush_started
    
    if _flush_started:
        return
    
    with _redis_lock:
        if _flush_started:
            return
        
        _flush_stop_event.clear()
        _flush_thread = threading.Thread(target=_periodic_flush_worker, daemon=True)
        _flush_thread.start()
        _flush_started = True
        
        # Register shutdown hook
        atexit.register(_shutdown_flush)
        
        logger.info(f"Started periodic cost flush thread (interval: {FLUSH_INTERVAL}s)")


def _periodic_flush_worker():
    """Worker thread that flushes costs to BigQuery periodically."""
    while not _flush_stop_event.is_set():
        # Wait for the interval (or until stopped)
        if _flush_stop_event.wait(timeout=FLUSH_INTERVAL):
            break  # Stop event was set
        
        try:
            logger.info("Periodic cost flush triggered")
            flush_costs_to_bigquery()
        except Exception as e:
            logger.error(f"Error in periodic cost flush: {e}")


def _shutdown_flush():
    """Shutdown hook: flush all costs to BigQuery before exit."""
    global _flush_stop_event
    
    logger.info("Server shutdown: flushing costs to BigQuery...")
    _flush_stop_event.set()
    
    try:
        flush_costs_to_bigquery()
        logger.info("Cost flush completed on shutdown")
    except Exception as e:
        logger.error(f"Error flushing costs on shutdown: {e}")


def calculate_translation_cost(character_count: int) -> float:
    """Calculate Google Translate API cost.
    
    Google Translate charges $20 per million characters.
    
    Args:
        character_count: Total number of characters translated
    
    Returns:
        Cost in USD
    """
    return (character_count / 1_000_000) * 20.0


def _track_in_memory(
    user_id: str,
    phase: str,
    vendor: str,
    cost: float,
    metadata: Optional[Dict[str, Any]] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    search_queries: Optional[int] = None,
) -> None:
    """Track cost in memory (fallback when Redis unavailable).
    
    Each request is stored with (user_id, phase, vendor) - aggregation happens in BigQuery.
    """
    with _memory_lock:
        # Update global total for quick pending cost display
        _memory_store["total"] += cost
        
        # Store request for BigQuery batch insert - this is the source of truth
        request_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "phase": phase,
            "vendor": vendor,
            "cost": cost,
            "request_count": 1,
            "metadata": metadata
        }
        if input_tokens:
            request_data["input_tokens"] = input_tokens
        if output_tokens:
            request_data["output_tokens"] = output_tokens
        if search_queries is not None and search_queries > 0:
            request_data["search_queries"] = search_queries
        if metadata and "character_count" in metadata:
            request_data["character_count"] = metadata["character_count"]
        
        _memory_store["requests"].append(request_data)


def _track_in_redis(
    redis_client,
    user_id: str,
    phase: str,
    vendor: str,
    cost: float,
    metadata: Optional[Dict[str, Any]] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    search_queries: Optional[int] = None,
) -> None:
    """Track cost in Redis using atomic operations.
    
    Each request is stored with (user_id, phase, vendor) - aggregation happens in BigQuery.
    Redis just keeps a running total for quick display and queues requests for batch insert.
    """
    import json
    
    try:
        pipe = redis_client.pipeline()
        
        # Increment global total for quick pending cost display
        pipe.incrbyfloat(TOTAL_KEY, cost)
        
        # Increment per-user total for quick user cost display
        pipe.incrbyfloat(f"{USER_PREFIX}{user_id}:total", cost)
        pipe.sadd(f"{REDIS_PREFIX}users", user_id)
        
        # Store request for BigQuery batch insert - this is the source of truth
        request_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "phase": phase,
            "vendor": vendor,
            "cost": cost,
            "request_count": 1,
            "metadata": metadata
        }
        if input_tokens:
            request_data["input_tokens"] = input_tokens
        if output_tokens:
            request_data["output_tokens"] = output_tokens
        if search_queries is not None and search_queries > 0:
            request_data["search_queries"] = search_queries
        if metadata and "character_count" in metadata:
            request_data["character_count"] = metadata["character_count"]
        
        pipe.rpush(f"{REDIS_PREFIX}requests", json.dumps(request_data))
        
        pipe.execute()
        
    except Exception as e:
        logger.error(f"Error tracking cost in Redis: {e}")
        # Fall back to memory tracking
        _track_in_memory(user_id, phase, vendor, cost, metadata, input_tokens, output_tokens, search_queries)


def track_api_cost(
    user_id: str,
    phase: str,
    vendor: str,
    cost: float,
    metadata: Optional[Dict[str, Any]] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    search_queries: Optional[int] = None,
) -> None:
    """Track cost for an API call.
    
    Uses Redis if available, otherwise falls back to in-memory tracking.
    
    Args:
        user_id: User ID (required - all API calls require authentication)
        phase: Processing phase (background, draft, feedback, refine, translate, extract)
        vendor: AI vendor (openai, anthropic, gemini, etc.)
        cost: Cost in USD
        metadata: Additional metadata (character_count for translate, etc.)
        input_tokens: Number of input/prompt tokens (for AI services)
        output_tokens: Number of output/completion tokens (for AI services)
        search_queries: Number of web/grounding search calls (Gemini, Grok)
    """
    # Ensure flush thread is running
    _ensure_flush_thread()
    
    redis_client = _get_redis_client()
    
    if redis_client is not None:
        _track_in_redis(redis_client, user_id, phase, vendor, cost, metadata, input_tokens, output_tokens, search_queries)
    else:
        _track_in_memory(user_id, phase, vendor, cost, metadata, input_tokens, output_tokens, search_queries)


def _get_summary_from_memory() -> Dict[str, Any]:
    """Get pending cost summary from in-memory store.
    
    Returns just the pending totals - detailed aggregation happens in BigQuery.
    """
    with _memory_lock:
        # Aggregate pending requests by user
        pending_by_user = {}
        for req in _memory_store["requests"]:
            uid = req.get("user_id", "anonymous")
            if uid not in pending_by_user:
                pending_by_user[uid] = 0.0
            pending_by_user[uid] += req.get("cost", 0.0)
        
        return {
            "pending_cost": _memory_store["total"],
            "pending_requests": len(_memory_store["requests"]),
            "pending_by_user": pending_by_user,
            "storage": "memory"
        }


def _get_summary_from_redis(redis_client) -> Dict[str, Any]:
    """Get pending cost summary from Redis.
    
    Returns just the pending totals - detailed aggregation happens in BigQuery.
    """
    try:
        # Get pending totals by user
        users = redis_client.smembers(f"{REDIS_PREFIX}users") or set()
        pending_by_user = {}
        for user_id in users:
            user_total = float(redis_client.get(f"{USER_PREFIX}{user_id}:total") or 0)
            if user_total > 0:
                pending_by_user[user_id] = user_total
        
        return {
            "pending_cost": float(redis_client.get(TOTAL_KEY) or 0),
            "pending_requests": redis_client.llen(f"{REDIS_PREFIX}requests"),
            "pending_by_user": pending_by_user,
            "storage": "redis"
        }
        
    except Exception as e:
        logger.error(f"Error getting cost summary from Redis: {e}")
        # Fall back to memory
        return _get_summary_from_memory()


def get_cost_summary() -> Dict[str, Any]:
    """Get current cost summary (pending data not yet flushed to BigQuery).
    
    Returns data from Redis if available, otherwise from memory.
    
    Returns:
        Dictionary with cost summary
    """
    redis_client = _get_redis_client()
    
    if redis_client is not None:
        return _get_summary_from_redis(redis_client)
    else:
        return _get_summary_from_memory()


def get_user_monthly_cost(user_id: str, months_back: int = 1) -> Dict[str, Any]:
    """Get user's total cost from BigQuery for the last N months.
    
    This queries the partitioned BigQuery table efficiently.
    
    Args:
        user_id: User ID to query
        months_back: Number of months to look back (default: 1)
    
    Returns:
        Dictionary with total_cost, by_phase, by_vendor breakdown, and period info
    """
    client = _get_bigquery_client()
    if client is None:
        return {"error": "BigQuery not available", "total_cost": 0.0}
    
    # Ensure table exists before querying
    if not _ensure_bigquery_table():
        return {"error": "BigQuery table not available", "total_cost": 0.0}
    
    try:
        from google.cloud import bigquery
        
        # Query for phase breakdown
        phase_query = f"""
        SELECT 
            phase,
            SUM(cost) as total_cost,
            SUM(request_count) as total_requests,
            SUM(COALESCE(input_tokens, 0)) as input_tokens,
            SUM(COALESCE(output_tokens, 0)) as output_tokens
        FROM `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}`
        WHERE user_id = @user_id
          AND timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL @months_back MONTH))
        GROUP BY phase
        """
        
        # Query for vendor breakdown
        vendor_query = f"""
        SELECT 
            vendor,
            SUM(cost) as total_cost,
            SUM(request_count) as total_requests,
            SUM(COALESCE(input_tokens, 0)) as input_tokens,
            SUM(COALESCE(output_tokens, 0)) as output_tokens
        FROM `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}`
        WHERE user_id = @user_id
          AND timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL @months_back MONTH))
        GROUP BY vendor
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("months_back", "INT64", months_back),
            ]
        )
        
        # Run both queries
        phase_results = client.query(phase_query, job_config=job_config).result()
        vendor_results = client.query(vendor_query, job_config=job_config).result()
        
        total_cost = 0.0
        total_requests = 0
        total_input_tokens = 0
        total_output_tokens = 0
        by_phase = {}
        by_vendor = {}
        
        for row in phase_results:
            phase_cost = float(row.total_cost or 0)
            total_cost += phase_cost
            total_requests += int(row.total_requests or 0)
            total_input_tokens += int(row.input_tokens or 0)
            total_output_tokens += int(row.output_tokens or 0)
            by_phase[row.phase] = {
                "total_cost": phase_cost,
                "request_count": int(row.total_requests or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0)
            }
        
        for row in vendor_results:
            by_vendor[row.vendor] = {
                "total_cost": float(row.total_cost or 0),
                "request_count": int(row.total_requests or 0),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0)
            }
        
        return {
            "user_id": user_id,
            "period_months": months_back,
            "total_cost": total_cost,
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "by_phase": by_phase,
            "by_vendor": by_vendor
        }
        
    except Exception as e:
        logger.error(f"Error querying BigQuery for user costs: {e}")
        return {"error": str(e), "total_cost": 0.0}


def get_global_monthly_cost(months_back: int = 1) -> Dict[str, Any]:
    """Get global cost statistics from BigQuery for the last N months.
    
    Args:
        months_back: Number of months to look back (default: 1)
    
    Returns:
        Dictionary with total_cost, by_vendor, by_user breakdown
    """
    client = _get_bigquery_client()
    if client is None:
        return {"error": "BigQuery not available", "total_cost": 0.0}
    
    # Ensure table exists before querying
    if not _ensure_bigquery_table():
        return {"error": "BigQuery table not available", "total_cost": 0.0}
    
    try:
        from google.cloud import bigquery
        
        # Get totals by vendor
        query = f"""
        SELECT 
            vendor,
            SUM(cost) as total_cost,
            SUM(request_count) as total_requests,
            COUNT(DISTINCT user_id) as unique_users
        FROM `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}`
        WHERE timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL @months_back MONTH))
        GROUP BY vendor
        ORDER BY total_cost DESC
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("months_back", "INT64", months_back),
            ]
        )
        
        results = client.query(query, job_config=job_config).result()
        
        total_cost = 0.0
        total_requests = 0
        by_vendor = {}
        
        for row in results:
            vendor_cost = float(row.total_cost or 0)
            vendor_requests = int(row.total_requests or 0)
            total_cost += vendor_cost
            total_requests += vendor_requests
            by_vendor[row.vendor] = {
                "total_cost": vendor_cost,
                "request_count": vendor_requests,
                "unique_users": row.unique_users
            }
        
        return {
            "period_months": months_back,
            "total_cost": total_cost,
            "total_requests": total_requests,
            "by_vendor": by_vendor
        }
        
    except Exception as e:
        logger.error(f"Error querying BigQuery for global costs: {e}")
        return {"error": str(e), "total_cost": 0.0}


def get_user_daily_costs(user_id: str, months_back: int = 1) -> Dict[str, Any]:
    """Get user's daily cost breakdown from BigQuery.
    
    Args:
        user_id: User ID to query
        months_back: Number of months to look back (default: 1)
    
    Returns:
        Dictionary with daily breakdown
    """
    client = _get_bigquery_client()
    if client is None:
        return {"error": "BigQuery not available", "days": []}
    
    # Ensure table exists before querying
    if not _ensure_bigquery_table():
        return {"error": "BigQuery table not available", "days": []}
    
    try:
        from google.cloud import bigquery
        
        query = f"""
        SELECT 
            DATE(timestamp) as date,
            SUM(cost) as total_cost,
            SUM(request_count) as request_count
        FROM `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}`
        WHERE user_id = @user_id
          AND timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL @months_back MONTH))
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("months_back", "INT64", months_back),
            ]
        )
        
        results = client.query(query, job_config=job_config).result()
        
        days = []
        for row in results:
            days.append({
                "date": row.date.isoformat() if row.date else None,
                "total_cost": float(row.total_cost or 0),
                "request_count": int(row.request_count or 0),
            })
        
        return {
            "user_id": user_id,
            "period_months": months_back,
            "days": days,
        }
        
    except Exception as e:
        logger.error(f"Error querying BigQuery for daily costs: {e}")
        return {"error": str(e), "days": []}


def _get_pending_requests_from_memory() -> List[Dict[str, Any]]:
    """Get pending requests from memory store."""
    with _memory_lock:
        requests = _memory_store["requests"].copy()
        return requests


def _get_pending_requests_from_redis(redis_client) -> List[Dict[str, Any]]:
    """Get pending requests from Redis."""
    import json
    
    try:
        # Get all pending requests
        raw_requests = redis_client.lrange(f"{REDIS_PREFIX}requests", 0, -1)
        return [json.loads(r) for r in raw_requests]
    except Exception as e:
        logger.error(f"Error getting pending requests from Redis: {e}")
        return []


def _reset_memory_store() -> None:
    """Reset in-memory cost store after flush."""
    with _memory_lock:
        _memory_store["total"] = 0.0
        _memory_store["services"] = {}
        _memory_store["users"] = {}
        _memory_store["requests"] = []


def _reset_redis_counters(redis_client) -> None:
    """Reset all cost counters in Redis after flush."""
    try:
        # Get all keys to delete
        keys_to_delete = []
        
        # Add global total
        keys_to_delete.append(TOTAL_KEY)
        
        # Add service keys
        services = redis_client.smembers(f"{REDIS_PREFIX}services") or set()
        for service in services:
            keys_to_delete.append(f"{SERVICE_PREFIX}{service}:total")
            keys_to_delete.append(f"{SERVICE_PREFIX}{service}:count")
        
        # Add user keys
        users = redis_client.smembers(f"{REDIS_PREFIX}users") or set()
        for user_id in users:
            keys_to_delete.append(f"{USER_PREFIX}{user_id}:total")
            for service in services:
                keys_to_delete.append(f"{USER_PREFIX}{user_id}:service:{service}:total")
                keys_to_delete.append(f"{USER_PREFIX}{user_id}:service:{service}:count")
        
        # Delete tracking sets and request list
        keys_to_delete.append(f"{REDIS_PREFIX}services")
        keys_to_delete.append(f"{REDIS_PREFIX}users")
        keys_to_delete.append(f"{REDIS_PREFIX}requests")
        
        # Delete all keys
        if keys_to_delete:
            redis_client.delete(*keys_to_delete)
        
    except Exception as e:
        logger.error(f"Error resetting Redis counters: {e}")


def flush_costs_to_bigquery(reset_after_flush: bool = True, save_completing_user_id: Optional[str] = None) -> Dict[str, Any]:
    """Flush accumulated costs from Redis/memory to BigQuery.
    
    Inserts individual request rows to the partitioned BigQuery table.
    
    Args:
        reset_after_flush: If True, reset counters after successful flush
        save_completing_user_id: If set, rows for this user get document_saved=True; others get False.
                                 Used when flushing on letter completion.
    
    Returns:
        Summary of what was flushed
    """
    # Get pending requests
    redis_client = _get_redis_client()
    if redis_client is not None:
        pending_requests = _get_pending_requests_from_redis(redis_client)
    else:
        pending_requests = _get_pending_requests_from_memory()
    
    if not pending_requests:
        return {"status": "skipped", "reason": "No costs to flush", "rows_inserted": 0}
    
    client = _get_bigquery_client()
    if client is None:
        return {"status": "error", "error": "BigQuery not available", "rows_pending": len(pending_requests)}
    
    try:
        # Ensure table exists
        if not _ensure_bigquery_table():
            return {"status": "error", "error": "Failed to create BigQuery table"}
        
        # Prepare rows for insertion
        table_id = f"{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}"
        
        rows_to_insert = []
        for req in pending_requests:
            row = {
                "timestamp": req["timestamp"],
                "user_id": req.get("user_id", "anonymous"),
                "phase": req["phase"],
                "vendor": req["vendor"],
                "cost": req["cost"],
                "request_count": req.get("request_count", 1),
            }
            if "input_tokens" in req:
                row["input_tokens"] = req["input_tokens"]
            if "output_tokens" in req:
                row["output_tokens"] = req["output_tokens"]
            if "character_count" in req:
                row["character_count"] = req["character_count"]
            if "search_queries" in req and req["search_queries"] is not None:
                row["search_queries"] = req["search_queries"]
            if save_completing_user_id is not None:
                row["document_saved"] = req.get("user_id") == save_completing_user_id

            rows_to_insert.append(row)
        
        # Batch insert to BigQuery
        errors = client.insert_rows_json(table_id, rows_to_insert)
        
        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
            return {
                "status": "partial",
                "rows_attempted": len(rows_to_insert),
                "errors": errors[:5],  # Limit error output
            }
        
        logger.info(f"Flushed {len(rows_to_insert)} cost records to BigQuery")
        
        # Reset counters after successful flush
        if reset_after_flush:
            if redis_client is not None:
                _reset_redis_counters(redis_client)
            _reset_memory_store()  # Always reset memory too
            logger.info("Reset cost counters after flush")
        
        # Calculate totals for response
        total_cost = sum(r["cost"] for r in rows_to_insert)
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rows_inserted": len(rows_to_insert),
            "total_cost_flushed": total_cost,
        }
        
    except Exception as e:
        logger.error(f"Error flushing costs to BigQuery: {e}")
        return {"status": "error", "error": str(e), "rows_pending": len(pending_requests)}


def flush_on_letter_completion(user_id: str) -> Dict[str, Any]:
    """Trigger a flush when a letter is completed.
    
    This ensures the user's costs are recorded immediately when they finish.
    
    Args:
        user_id: The user who completed the letter
    
    Returns:
        Flush result summary
    """
    logger.info(f"Letter completion flush triggered for user {user_id}")
    return flush_costs_to_bigquery(reset_after_flush=True, save_completing_user_id=user_id)
