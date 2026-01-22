#!/usr/bin/env python3
"""
Test script for cost tracking functionality.

This script demonstrates:
1. Calculating translation costs
2. Tracking API costs
3. Retrieving cost summaries
"""

import sys
from pathlib import Path

# Add the letter_writer module to the path
sys.path.insert(0, str(Path(__file__).parent))

from letter_writer.cost_tracker import (
    calculate_translation_cost,
    track_api_cost,
    get_cost_summary,
    get_cost_log_path,
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


def test_cost_tracking():
    """Test cost tracking functionality."""
    print("=" * 60)
    print("Testing Cost Tracking")
    print("=" * 60)
    
    print(f"Cost log path: {get_cost_log_path()}\n")
    
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
    
    print("Tracking example API costs...\n")
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
    print("Cost Summary")
    print("=" * 60)
    
    summary = get_cost_summary()
    
    print(f"Total Cost: ${summary['total_cost']:.4f}")
    print(f"Total Requests: {summary['total_requests']}")
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
            for service, service_data in user_data['by_service'].items():
                print(f"    - {service:28s} ${service_data['total_cost']:>8.4f} ({service_data['request_count']:>4} requests)")
        print()
    
    print("✓ Cost summary retrieved successfully!\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("COST TRACKING TEST SUITE")
    print("=" * 60 + "\n")
    
    try:
        test_translation_cost_calculation()
        test_cost_tracking()
        test_cost_summary()
        
        print("=" * 60)
        print("ALL TESTS PASSED! ✓")
        print("=" * 60 + "\n")
        
        print(f"Cost tracking data saved to: {get_cost_log_path()}")
        print("You can view the cost data by reading this JSON file.\n")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
