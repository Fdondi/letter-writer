#!/usr/bin/env python3
"""
Test script for cost tracking functionality.

This script demonstrates:
1. Calculating translation costs
2. Tracking API costs in Redis/memory
3. Retrieving cost summaries
4. Flushing costs to BigQuery

Requirements:
- Redis server running (optional - falls back to memory)
- For BigQuery flush tests, set GOOGLE_CLOUD_PROJECT and BIGQUERY_DATASET
"""

import os
import sys
import logging
from pathlib import Path

# Add the letter_writer module to the path
sys.path.insert(0, str(Path(__file__).parent))

from letter_writer.cost_tracker import (
    calculate_translation_cost,
    track_api_cost,
    get_cost_summary,
    flush_costs_to_bigquery,
    get_user_monthly_cost,
    get_global_monthly_cost,
    _get_redis_client,
)

logger = logging.getLogger(__name__)


def test_translation_cost_calculation():
    """Test translation cost calculation."""
    logger.info("%s", "=" * 60)
    logger.info("Testing Translation Cost Calculation")
    logger.info("%s", "=" * 60)
    
    # Test cases: (character_count, expected_cost)
    test_cases = [
        (1_000_000, 20.00),      # 1 million characters = $20
        (500_000, 10.00),        # 500k characters = $10
        (100_000, 2.00),         # 100k characters = $2
        (50_000, 1.00),          # 50k characters = $1
        (10_000, 0.20),          # 10k characters = $0.20
        (1_000, 0.02),           # 1k characters = $0.02
        (100, 0.002),            # 100 characters = $0.002
    ]
    
    for char_count, expected_cost in test_cases:
        cost = calculate_translation_cost(char_count)
        logger.info("%10s characters -> $%8.4f (expected: $%.4f)", f"{char_count:,}", cost, expected_cost)
        assert abs(cost - expected_cost) < 0.0001, f"Cost mismatch: {cost} != {expected_cost}"
    
    logger.info("\n%s\n", "✓ All translation cost calculations passed!")


def test_storage_backend():
    """Test storage backend detection."""
    logger.info("%s", "=" * 60)
    logger.info("Testing Storage Backend")
    logger.info("%s", "=" * 60)
    
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    logger.info("Redis URL: %s\n", redis_url)
    
    client = _get_redis_client()
    if client is None:
        logger.warning("Redis not available - using in-memory fallback")
        logger.warning("To use Redis: start Redis or set REDIS_URL environment variable\n")
        return "memory"
    
    logger.info("✓ Redis connection successful!\n")
    return "redis"


def test_cost_tracking(storage_type):
    """Test cost tracking functionality."""
    logger.info("%s", "=" * 60)
    logger.info("Testing Cost Tracking (%s)", storage_type)
    logger.info("%s", "=" * 60)
    
    # Track some example costs
    examples = [
        {
            "phase": "translate",
            "vendor": "google_translate",
            "cost": 0.02,
            "metadata": {"character_count": 1000},
            "user_id": "test_user_123",
        },
        {
            "phase": "background",
            "vendor": "openai",
            "cost": 0.15,
            "user_id": "test_user_123",
        },
        {
            "phase": "draft",
            "vendor": "anthropic",
            "cost": 0.50,
            "user_id": "test_user_456",
        },
        {
            "phase": "refine",
            "vendor": "gemini",
            "cost": 0.35,
            "search_queries": 2,
            "user_id": "test_user_123",
        },
    ]
    
    logger.info("Tracking example API costs (%s)...\n", storage_type)
    for example in examples:
        track_api_cost(
            user_id=example["user_id"],
            phase=example["phase"],
            vendor=example["vendor"],
            cost=example["cost"],
            metadata=example.get("metadata"),
            search_queries=example.get("search_queries"),
        )
        logger.info("  ✓ Tracked: %s/%s - $%.4f", example["phase"], example["vendor"], example["cost"])
    
    logger.info("\n%s\n", "✓ Cost tracking completed!")


def test_cost_summary():
    """Test cost summary retrieval."""
    logger.info("%s", "=" * 60)
    logger.info("Pending Cost Summary")
    logger.info("%s", "=" * 60)
    
    summary = get_cost_summary()
    
    logger.info("Storage: %s", summary.get("storage", "unknown"))
    logger.info("Total Cost: $%.4f", summary["total_cost"])
    logger.info("Pending Requests: %s", summary.get("pending_requests", 0))
    logger.info("")
    
    if summary.get('by_service'):
        logger.info("Costs by Service:")
        logger.info("%s", "-" * 60)
        for service, data in summary['by_service'].items():
            logger.info("  %-30s $%8.4f (%4s requests)", service, data["total_cost"], data["request_count"])
        logger.info("")
    
    if summary.get('by_user'):
        logger.info("Costs by User:")
        logger.info("%s", "-" * 60)
        for user_id, user_data in summary['by_user'].items():
            logger.info("  %s: $%.4f", user_id, user_data["total_cost"])
            for service, service_data in user_data.get('by_service', {}).items():
                logger.info("    - %-28s $%8.4f (%4s requests)", service, service_data["total_cost"], service_data["request_count"])
        logger.info("")
    
    logger.info("✓ Cost summary retrieved successfully!\n")


def test_bigquery_flush(skip_if_no_credentials=True):
    """Test flushing costs to BigQuery."""
    logger.info("%s", "=" * 60)
    logger.info("BigQuery Flush Test")
    logger.info("%s", "=" * 60)
    
    # Check if BigQuery credentials are available
    if skip_if_no_credentials:
        project = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            logger.warning("Skipping BigQuery flush - no credentials")
            logger.warning("Set BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT to enable\n")
            return
    
    logger.info("Flushing costs to BigQuery...")
    result = flush_costs_to_bigquery(reset_after_flush=True)
    
    logger.info("Status: %s", result.get("status"))
    if result.get('status') == 'success':
        logger.info("Rows inserted: %s", result.get("rows_inserted", 0))
        logger.info("Total cost flushed: $%.4f", result.get("total_cost_flushed", 0))
    elif result.get('status') == 'skipped':
        logger.warning("Reason: %s", result.get("reason"))
    else:
        logger.error("Error: %s", result.get("error"))
        if result.get('rows_pending'):
            logger.error("Rows pending: %s", result.get("rows_pending"))
    
    logger.info("")


def test_bigquery_query(skip_if_no_credentials=True):
    """Test querying costs from BigQuery."""
    logger.info("%s", "=" * 60)
    logger.info("BigQuery Query Test")
    logger.info("%s", "=" * 60)
    
    # Check if BigQuery credentials are available
    if skip_if_no_credentials:
        project = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            logger.warning("Skipping BigQuery query - no credentials")
            logger.warning("Set BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT to enable\n")
            return
    
    logger.info("Querying user costs from BigQuery...")
    user_result = get_user_monthly_cost("test_user_123", months_back=1)
    
    if user_result.get("error"):
        logger.error("  Error: %s", user_result.get("error"))
    else:
        logger.info("  User: %s", user_result.get("user_id"))
        logger.info("  Total Cost: $%.4f", user_result.get("total_cost", 0))
        logger.info("  Total Requests: %s", user_result.get("total_requests", 0))
    
    logger.info("\nQuerying global costs from BigQuery...")
    global_result = get_global_monthly_cost(months_back=1)
    
    if global_result.get("error"):
        logger.error("  Error: %s", global_result.get("error"))
    else:
        logger.info("  Total Cost: $%.4f", global_result.get("total_cost", 0))
        logger.info("  Total Requests: %s", global_result.get("total_requests", 0))
        if global_result.get("by_service"):
            logger.info("  By Service:")
            for service, data in global_result["by_service"].items():
                logger.info("    - %s: $%.4f", service, data["total_cost"])
    
    logger.info("")


def main():
    """Run all tests."""
    logger.info("\n%s", "=" * 60)
    logger.info("COST TRACKING TEST SUITE")
    logger.info("%s\n", "=" * 60)
    
    try:
        test_translation_cost_calculation()
        storage_type = test_storage_backend()
        
        test_cost_tracking(storage_type)
        test_cost_summary()
        test_bigquery_flush(skip_if_no_credentials=True)
        test_bigquery_query(skip_if_no_credentials=True)
        
        logger.info("%s", "=" * 60)
        logger.info("ALL TESTS COMPLETED! ✓")
        logger.info("%s\n", "=" * 60)
        
        if storage_type == "redis":
            logger.info("Cost tracking is using Redis for fast atomic operations.")
        else:
            logger.info("Cost tracking is using in-memory storage (Redis unavailable).")
        
        logger.info("Costs are flushed to BigQuery:")
        logger.info("  - On letter completion")
        logger.info("  - Every 30 minutes (configurable via COST_FLUSH_INTERVAL_SECONDS)")
        logger.info("  - On server shutdown")
        logger.info("")
        logger.info("BigQuery table: {project}.{dataset}.api_costs")
        logger.info("  - Partitioned by: month (timestamp)")
        logger.info("  - Clustered by: user_id, service")
        logger.info("")
        
    except Exception as e:
        logger.exception("\nTest failed: %s", e)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
