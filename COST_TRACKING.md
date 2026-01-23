# API Cost Tracking

Cost tracking system using Redis/memory for fast operations and BigQuery for analytics.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   API Request   │────────>│  Redis / Memory │────────>│    BigQuery     │
│                 │  INCR   │  (fast atomic   │  Batch  │  (analytics &   │
│  translate,     │         │   counters)     │  Insert │   reporting)    │
│  background,    │         │                 │         │                 │
│  draft, refine  │         └─────────────────┘         └─────────────────┘
└─────────────────┘                 │                           │
                                    │                           │
                            ┌───────┴───────┐           ┌───────┴───────┐
                            │ Flush Triggers │           │ BigQuery Table│
                            │               │           │               │
                            │ • Letter done │           │ • Partitioned │
                            │ • 30 min timer│           │   by month    │
                            │ • Shutdown    │           │ • Clustered   │
                            └───────────────┘           │   by user_id  │
                                                        └───────────────┘
```

## Why BigQuery?

- **Analytics-optimized**: Designed for aggregations and reporting
- **Cost-effective**: Partitioning by month reduces data scanned
- **Scalable**: Handles billions of rows efficiently
- **SQL queries**: Easy to build reports and dashboards

## Storage Backends (Real-time)

### Redis (Primary)
- Fast atomic INCR operations
- Distributed across server instances

### In-Memory (Fallback)
- Thread-safe, always available
- Falls back automatically if Redis unavailable

## BigQuery Table Schema

**Table**: `{project}.{dataset}.api_costs`

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | TIMESTAMP | When the cost was incurred |
| `user_id` | STRING | User identifier |
| `service` | STRING | Service name (translate, background_openai, etc.) |
| `cost` | FLOAT64 | Cost in USD |
| `request_count` | INT64 | Number of requests |
| `character_count` | INT64 | Characters (for translation) |
| `metadata` | JSON | Additional request metadata |

### Partitioning & Clustering

- **Partitioned by**: `timestamp` (monthly granularity)
- **Clustered by**: `user_id`, `service`

This ensures queries for a specific user's monthly costs only scan relevant data.

## Cost Calculation

### Translation Costs
- **Service**: Google Translate API
- **Rate**: $20 per million characters
- **Formula**: `cost = (character_count / 1,000,000) * 20`

### AI Model Costs
Tracked automatically by AI client modules (token-based pricing).

## API Endpoints

### Get Pending Costs (Redis/Memory)
```
GET /api/costs/pending/
```

Returns costs accumulated since last flush:
```json
{
  "total_cost": 1.02,
  "pending_requests": 4,
  "storage": "redis",
  "by_service": {...},
  "by_user": {...}
}
```

### Flush to BigQuery
```
POST /api/costs/flush/
```

Forces immediate flush:
```json
{
  "status": "success",
  "rows_inserted": 4,
  "total_cost_flushed": 1.02
}
```

### Get User Costs (from BigQuery)
```
GET /api/costs/user/?months=1
```

Returns user's costs for the last N months:
```json
{
  "user_id": "abc123",
  "period_months": 1,
  "total_cost": 25.50,
  "total_requests": 150,
  "by_service": {
    "translate": {"total_cost": 5.00, "request_count": 50},
    "draft_anthropic": {"total_cost": 20.50, "request_count": 100}
  }
}
```

### Get Global Costs (from BigQuery)
```
GET /api/costs/global/?months=1
```

Returns global statistics:
```json
{
  "period_months": 1,
  "total_cost": 1250.00,
  "total_requests": 5000,
  "by_service": {
    "translate": {"total_cost": 250.00, "request_count": 2500, "unique_users": 50},
    "background_openai": {"total_cost": 500.00, "request_count": 1000, "unique_users": 45}
  }
}
```

## Configuration

### Environment Variables

```bash
# Redis (optional - falls back to memory)
REDIS_URL="redis://localhost:6379/0"

# BigQuery
BIGQUERY_PROJECT="your-gcp-project"      # or GOOGLE_CLOUD_PROJECT
BIGQUERY_DATASET="letter_writer"          # default
BIGQUERY_TABLE="api_costs"                # default
BIGQUERY_LOCATION="US"                    # for dataset creation

# Flush interval
COST_FLUSH_INTERVAL_SECONDS=1800          # default: 30 minutes
```

## Flush Triggers

Costs are flushed from Redis/memory to BigQuery:

1. **Letter completion**: When user clicks "Save & Copy" (clears session)
2. **Periodic timer**: Every 30 minutes (configurable)
3. **Server shutdown**: Via `atexit` hook

## Example Queries

### User's Monthly Spending
```sql
SELECT 
  DATE_TRUNC(timestamp, MONTH) as month,
  service,
  SUM(cost) as total_cost,
  SUM(request_count) as requests
FROM `project.dataset.api_costs`
WHERE user_id = 'user123'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 MONTH)
GROUP BY month, service
ORDER BY month DESC, total_cost DESC
```

### Top Users by Cost
```sql
SELECT 
  user_id,
  SUM(cost) as total_cost,
  SUM(request_count) as requests
FROM `project.dataset.api_costs`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 MONTH)
GROUP BY user_id
ORDER BY total_cost DESC
LIMIT 10
```

### Cost Trend by Service
```sql
SELECT 
  DATE_TRUNC(timestamp, DAY) as day,
  service,
  SUM(cost) as daily_cost
FROM `project.dataset.api_costs`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY day, service
ORDER BY day
```

## Graceful Degradation

- **Redis unavailable**: Uses in-memory tracking (automatic)
- **BigQuery unavailable**: Costs remain in Redis/memory until next flush attempt
- **No data loss**: Counters only reset after successful BigQuery insert

## Testing

```bash
# Start Redis (optional)
docker run -d -p 6379:6379 redis:alpine

# Run tests
python test_cost_tracking.py
```

## Monitoring

1. **Real-time**: `GET /api/costs/pending/` for pending data
2. **Historical**: Query BigQuery directly or use `/api/costs/user/` and `/api/costs/global/`
3. **BigQuery Console**: Build dashboards in Looker Studio
