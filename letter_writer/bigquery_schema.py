"""
BigQuery schema definitions for cost tracking.

This module defines the schema as code, making it:
- Version controlled
- Testable
- Self-documenting
"""

from typing import Dict, Any, List

# Table configuration
TABLE_CONFIG = {
    "dataset": "letter_writer",
    "table": "api_costs",
    "description": "API cost tracking for letter-writer application",
    "partitioning": {
        "type": "MONTH",
        "field": "timestamp",
    },
    "clustering": ["user_id", "phase", "vendor"],
}

# Valid phases for cost tracking
VALID_PHASES = ["background", "draft", "feedback", "refine", "translate", "extract"]

# Valid vendors
VALID_VENDORS = ["openai", "anthropic", "gemini", "mistral", "grok", "deepseek", "google_translate"]

# Schema definition
SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "timestamp",
        "type": "TIMESTAMP",
        "mode": "REQUIRED",
        "description": "When the API call was made (UTC)",
    },
    {
        "name": "user_id",
        "type": "STRING",
        "mode": "REQUIRED",
        "description": "User identifier (Google OAuth UID or 'anonymous')",
    },
    {
        "name": "phase",
        "type": "STRING",
        "mode": "REQUIRED",
        "description": "Processing phase (background, draft, feedback, refine, translate, extract)",
    },
    {
        "name": "vendor",
        "type": "STRING",
        "mode": "REQUIRED",
        "description": "AI vendor (openai, anthropic, gemini, mistral, grok, deepseek, google_translate)",
    },
    {
        "name": "cost",
        "type": "FLOAT64",
        "mode": "REQUIRED",
        "description": "Cost in USD",
    },
    {
        "name": "request_count",
        "type": "INT64",
        "mode": "REQUIRED",
        "description": "Number of API requests in this record",
    },
    {
        "name": "input_tokens",
        "type": "INT64",
        "mode": "NULLABLE",
        "description": "Number of input/prompt tokens (for AI services)",
    },
    {
        "name": "output_tokens",
        "type": "INT64",
        "mode": "NULLABLE",
        "description": "Number of output/completion tokens (for AI services)",
    },
    {
        "name": "character_count",
        "type": "INT64",
        "mode": "NULLABLE",
        "description": "Number of characters (for translation phase)",
    },
    {
        "name": "metadata",
        "type": "JSON",
        "mode": "NULLABLE",
        "description": "Additional request metadata",
    },
]


def get_bigquery_schema():
    """Get schema as BigQuery SchemaField objects.
    
    Returns:
        List of bigquery.SchemaField objects
    """
    from google.cloud import bigquery
    
    return [
        bigquery.SchemaField(
            name=field["name"],
            field_type=field["type"],
            mode=field["mode"],
            description=field.get("description", ""),
        )
        for field in SCHEMA
    ]


def get_create_table_sql(project: str, dataset: str = None, table: str = None) -> str:
    """Generate CREATE TABLE SQL statement.
    
    Useful for manual table creation or documentation.
    
    Args:
        project: GCP project ID
        dataset: Dataset name (default from TABLE_CONFIG)
        table: Table name (default from TABLE_CONFIG)
    
    Returns:
        SQL CREATE TABLE statement
    """
    dataset = dataset or TABLE_CONFIG["dataset"]
    table = table or TABLE_CONFIG["table"]
    table_id = f"`{project}.{dataset}.{table}`"
    
    # Build column definitions
    columns = []
    for field in SCHEMA:
        col_def = f"  {field['name']} {field['type']}"
        if field["mode"] == "REQUIRED":
            col_def += " NOT NULL"
        if field.get("description"):
            col_def += f" OPTIONS(description=\"{field['description']}\")"
        columns.append(col_def)
    
    columns_sql = ",\n".join(columns)
    
    partition_field = TABLE_CONFIG["partitioning"]["field"]
    partition_type = TABLE_CONFIG["partitioning"]["type"]
    clustering_fields = ", ".join(TABLE_CONFIG["clustering"])
    
    sql = f"""
CREATE TABLE IF NOT EXISTS {table_id} (
{columns_sql}
)
PARTITION BY DATE_TRUNC({partition_field}, {partition_type})
CLUSTER BY {clustering_fields}
OPTIONS(
  description="{TABLE_CONFIG['description']}"
);
""".strip()
    
    return sql


def print_schema_documentation():
    """Print schema documentation in markdown format."""
    print(f"# BigQuery Table: `{TABLE_CONFIG['dataset']}.{TABLE_CONFIG['table']}`")
    print()
    print(f"{TABLE_CONFIG['description']}")
    print()
    print("## Schema")
    print()
    print("| Column | Type | Mode | Description |")
    print("|--------|------|------|-------------|")
    for field in SCHEMA:
        print(f"| `{field['name']}` | {field['type']} | {field['mode']} | {field.get('description', '')} |")
    print()
    print("## Partitioning")
    print()
    print(f"- **Type**: {TABLE_CONFIG['partitioning']['type']}")
    print(f"- **Field**: `{TABLE_CONFIG['partitioning']['field']}`")
    print()
    print("## Clustering")
    print()
    print(f"- **Fields**: `{', '.join(TABLE_CONFIG['clustering'])}`")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--sql":
        project = sys.argv[2] if len(sys.argv) > 2 else "YOUR_PROJECT_ID"
        print(get_create_table_sql(project))
    else:
        print_schema_documentation()
