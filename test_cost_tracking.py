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


def test_translation_cost_calculation():
    """Test translation cost calculation."""
    print("=" * 60)
    print("Testing Translation Cost Calculation")
    print("=" * 60)
    
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
        print(f"{char_count:>10,} characters -> ${cost:>8.4f} (expected: ${expected_cost:.4f})")
        assert abs(cost - expected_cost) < 0.0001, f"Cost mismatch: {cost} != {expected_cost}"
    
    print("\n✓ All translation cost calculations passed!\n")


def test_storage_backend():
    """Test storage backend detection."""
    print("=" * 60)
    print("Testing Storage Backend")
    print("=" * 60)
    
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    print(f"Redis URL: {redis_url}\n")
    
    client = _get_redis_client()
    if client is None:
        print("ℹ Redis not available - using in-memory fallback")
        print("  To use Redis: start Redis or set REDIS_URL environment variable\n")
        return "memory"
    
    print("✓ Redis connection successful!\n")
    return "redis"


def test_cost_tracking(storage_type):
    """Test cost tracking functionality."""
    print("=" * 60)
    print(f"Testing Cost Tracking ({storage_type})")
    print("=" * 60)
    
    # Track some example costs
    examples = [
        {
            "service": "translate",
            "cost": 0.02,
            "metadata": {
                "character_count": 1000,
                "text_count": 1,
                "target_language": "de",
                "source_language": "en"
            },
            "user_id": "test_user_123"
        },
        {
            "service": "background_openai",
            "cost": 0.15,
            "metadata": {
                "vendor": "openai",
                "phase": "background"
            },
            "user_id": "test_user_123"
        },
        {
            "service": "draft_anthropic",
            "cost": 0.50,
            "metadata": {
                "vendor": "anthropic",
                "phase": "draft"
            },
            "user_id": "test_user_456"
        },
        {
            "service": "refine_gemini",
            "cost": 0.35,
            "metadata": {
                "vendor": "gemini",
                "phase": "refine",
                "fancy": False
            },
            "user_id": "test_user_123"
        },
    ]
    
    print(f"Tracking example API costs ({storage_type})...\n")
    for example in examples:
        track_api_cost(
            service=example["service"],
            cost=example["cost"],
            metadata=example["metadata"],
            user_id=example.get("user_id")
        )
        print(f"  ✓ Tracked: {example['service']} - ${example['cost']:.4f}")
    
    print("\n✓ Cost tracking completed!\n")


def test_cost_summary():
    """Test cost summary retrieval."""
    print("=" * 60)
    print("Pending Cost Summary")
    print("=" * 60)
    
    summary = get_cost_summary()
    
    print(f"Storage: {summary.get('storage', 'unknown')}")
    print(f"Total Cost: ${summary['total_cost']:.4f}")
    print(f"Pending Requests: {summary.get('pending_requests', 0)}")
    print()
    
    if summary.get('by_service'):
        print("Costs by Service:")
        print("-" * 60)
        for service, data in summary['by_service'].items():
            print(f"  {service:30s} ${data['total_cost']:>8.4f} ({data['request_count']:>4} requests)")
        print()
    
    if summary.get('by_user'):
        print("Costs by User:")
        print("-" * 60)
        for user_id, user_data in summary['by_user'].items():
            print(f"  {user_id}: ${user_data['total_cost']:.4f}")
            for service, service_data in user_data.get('by_service', {}).items():
                print(f"    - {service:28s} ${service_data['total_cost']:>8.4f} ({service_data['request_count']:>4} requests)")
        print()
    
    print("✓ Cost summary retrieved successfully!\n")


def test_bigquery_flush(skip_if_no_credentials=True):
    """Test flushing costs to BigQuery."""
    print("=" * 60)
    print("BigQuery Flush Test")
    print("=" * 60)
    
    # Check if BigQuery credentials are available
    if skip_if_no_credentials:
        project = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            print("⚠ Skipping BigQuery flush - no credentials")
            print("  Set BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT to enable\n")
            return
    
    print("Flushing costs to BigQuery...")
    result = flush_costs_to_bigquery(reset_after_flush=True)
    
    print(f"Status: {result.get('status')}")
    if result.get('status') == 'success':
        print(f"Rows inserted: {result.get('rows_inserted', 0)}")
        print(f"Total cost flushed: ${result.get('total_cost_flushed', 0):.4f}")
    elif result.get('status') == 'skipped':
        print(f"Reason: {result.get('reason')}")
    else:
        print(f"Error: {result.get('error')}")
        if result.get('rows_pending'):
            print(f"Rows pending: {result.get('rows_pending')}")
    
    print()


def test_bigquery_query(skip_if_no_credentials=True):
    """Test querying costs from BigQuery."""
    print("=" * 60)
    print("BigQuery Query Test")
    print("=" * 60)
    
    # Check if BigQuery credentials are available
    if skip_if_no_credentials:
        project = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            print("⚠ Skipping BigQuery query - no credentials")
            print("  Set BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT to enable\n")
            return
    
    print("Querying user costs from BigQuery...")
    user_result = get_user_monthly_cost("test_user_123", months_back=1)
    
    if user_result.get("error"):
        print(f"  Error: {user_result.get('error')}")
    else:
        print(f"  User: {user_result.get('user_id')}")
        print(f"  Total Cost: ${user_result.get('total_cost', 0):.4f}")
        print(f"  Total Requests: {user_result.get('total_requests', 0)}")
    
    print("\nQuerying global costs from BigQuery...")
    global_result = get_global_monthly_cost(months_back=1)
    
    if global_result.get("error"):
        print(f"  Error: {global_result.get('error')}")
    else:
        print(f"  Total Cost: ${global_result.get('total_cost', 0):.4f}")
        print(f"  Total Requests: {global_result.get('total_requests', 0)}")
        if global_result.get("by_service"):
            print("  By Service:")
            for service, data in global_result["by_service"].items():
                print(f"    - {service}: ${data['total_cost']:.4f}")
    
    print()


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("COST TRACKING TEST SUITE")
    print("=" * 60 + "\n")
    
    try:
        test_translation_cost_calculation()
        storage_type = test_storage_backend()
        
        test_cost_tracking(storage_type)
        test_cost_summary()
        test_bigquery_flush(skip_if_no_credentials=True)
        test_bigquery_query(skip_if_no_credentials=True)
        
        print("=" * 60)
        print("ALL TESTS COMPLETED! ✓")
        print("=" * 60 + "\n")
        
        if storage_type == "redis":
            print("Cost tracking is using Redis for fast atomic operations.")
        else:
            print("Cost tracking is using in-memory storage (Redis unavailable).")
        
        print("Costs are flushed to BigQuery:")
        print("  - On letter completion")
        print("  - Every 30 minutes (configurable via COST_FLUSH_INTERVAL_SECONDS)")
        print("  - On server shutdown")
        print()
        print("BigQuery table: {project}.{dataset}.api_costs")
        print("  - Partitioned by: month (timestamp)")
        print("  - Clustered by: user_id, service")
        print()
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
