"""
Flexible Company Enrichment Pipeline

Dynamically generates input/output schemas based on CSV structure and research objectives.
Uses Claude API to intelligently design output schemas from natural language objectives.
"""

import os
import csv
import json
import sys
from typing import Dict, List, Any, Optional
from pathlib import Path
from pydantic import BaseModel, Field, create_model
from parallel import Parallel
from parallel.lib._parsing._task_run_result import task_run_result_parser
from parallel.types import TaskSpecParam
import anthropic


# ============================================================================
# SCHEMA GENERATION
# ============================================================================

def analyze_csv_structure(csv_path: str) -> Dict[str, Any]:
    """
    Analyze CSV structure to understand available columns.
    
    Returns:
        Dict with columns, sample data, and row count
    """
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
    if not rows:
        raise ValueError("CSV file is empty")
    
    columns = list(rows[0].keys())
    sample_rows = rows[:3]  # First 3 rows as examples
    
    return {
        'columns': columns,
        'sample_rows': sample_rows,
        'total_rows': len(rows),
        'all_rows': rows
    }


def generate_output_schema_with_claude(research_objective: str, csv_structure: Dict) -> Dict[str, Any]:
    """
    Use Claude API to generate an output schema based on research objective.
    
    Args:
        research_objective: Natural language description of what to research
        csv_structure: Structure info from analyze_csv_structure
    
    Returns:
        Dictionary representing the output schema
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    client = anthropic.Anthropic(api_key=api_key)
    
    # Build prompt for Claude
    prompt = f"""You are a data schema architect. Given a research objective and CSV structure, generate a JSON schema for the output fields.

CSV COLUMNS AVAILABLE:
{json.dumps(csv_structure['columns'], indent=2)}

SAMPLE DATA:
{json.dumps(csv_structure['sample_rows'][:2], indent=2)}

RESEARCH OBJECTIVE:
{research_objective}

Generate a JSON schema that defines the output fields needed to fulfill this research objective. Each field should have:
- A descriptive field name (snake_case)
- A type (string, array, integer, boolean)
- A clear description of what the field should contain
- For arrays, specify what items should be

IMPORTANT GUIDELINES:
1. Field names should be clear, concise, and use snake_case
2. Descriptions should guide the AI on what information to find
3. Use "string" for text, "array" for lists, "integer" for numbers, "boolean" for yes/no
4. For array fields, specify item type and what the array should contain
5. Include 5-10 fields that comprehensively address the research objective
6. Make descriptions specific enough to get high-quality results

Return ONLY a JSON object in this exact format:
{{
  "fields": [
    {{
      "name": "field_name",
      "type": "string",
      "description": "What this field should contain and how to find it",
      "required": true
    }},
    {{
      "name": "another_field",
      "type": "array",
      "items_type": "string",
      "description": "What this array should contain",
      "required": true
    }}
  ]
}}

Do not include any other text, explanations, or markdown formatting."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    response_text = message.content[0].text.strip()
    
    # Parse the JSON response
    try:
        schema_def = json.loads(response_text)
        return schema_def
    except json.JSONDecodeError as e:
        print(f"Failed to parse Claude's response as JSON: {e}")
        print(f"Response was: {response_text}")
        raise


def create_dynamic_input_model(csv_columns: List[str]) -> type[BaseModel]:
    """
    Create a dynamic Pydantic model for input based on CSV columns.
    
    Args:
        csv_columns: List of column names from CSV
    
    Returns:
        Dynamically created Pydantic BaseModel class
    """
    field_definitions = {}
    
    for col in csv_columns:
        # Create field with description
        field_definitions[col] = (
            str,
            Field(description=f"The {col.replace('_', ' ').lower()} from the CSV")
        )
    
    # Create the model dynamically
    DynamicInput = create_model(
        'DynamicInput',
        __doc__="Dynamically generated input schema from CSV columns",
        **field_definitions
    )
    
    return DynamicInput


def create_dynamic_output_model(schema_def: Dict[str, Any]) -> type[BaseModel]:
    """
    Create a dynamic Pydantic model for output based on schema definition.
    
    Args:
        schema_def: Schema definition from Claude API
    
    Returns:
        Dynamically created Pydantic BaseModel class
    """
    field_definitions = {}
    
    for field in schema_def['fields']:
        field_name = field['name']
        field_type = field['type']
        description = field['description']
        
        # Map JSON types to Python types
        if field_type == 'string':
            python_type = str
        elif field_type == 'array':
            python_type = List[str]  # Default to List[str]
        elif field_type == 'integer':
            python_type = int
        elif field_type == 'boolean':
            python_type = bool
        else:
            python_type = str  # Default fallback
        
        field_definitions[field_name] = (
            python_type,
            Field(description=description)
        )
    
    # Create the model dynamically
    DynamicOutput = create_model(
        'DynamicOutput',
        __doc__="Dynamically generated output schema from research objective",
        **field_definitions
    )
    
    return DynamicOutput


def build_task_spec_param(
    input_schema: type[BaseModel], 
    output_schema: type[BaseModel]
) -> TaskSpecParam:
    """Build a TaskSpecParam from input and output schemas."""
    return {
        "input_schema": {
            "type": "json",
            "json_schema": input_schema.model_json_schema(),
        },
        "output_schema": {
            "type": "json",
            "json_schema": output_schema.model_json_schema(),
        },
    }


# ============================================================================
# ENRICHMENT EXECUTION
# ============================================================================

def enrich_row(
    client: Parallel,
    row_data: Dict[str, str],
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    task_spec: TaskSpecParam,
    row_index: int,
    verbose: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Enrich a single row using the Parallel API.
    
    Args:
        client: Parallel API client
        row_data: Dictionary of row data from CSV
        input_model: Input Pydantic model
        output_model: Output Pydantic model
        task_spec: Task specification
        row_index: Index of the row being processed
        verbose: If True, print progress messages
    
    Returns:
        Enriched data dictionary or None if failed
    """
    def log(message):
        if verbose:
            print(message)
    
    try:
        log(f"  Creating task run for row {row_index}...")
        
        # Create input instance
        input_data = input_model(**row_data)
        
        # Create task run
        task_run = client.task_run.create(
            input=input_data.model_dump(),
            task_spec=task_spec,
            processor="core",
        )
        
        log(f"  Run ID: {task_run.run_id}")
        log(f"  Waiting for results...")
        
        # Wait for results
        run_result = client.task_run.result(task_run.run_id, api_timeout=3600)
        
        # Parse result
        parsed_result = task_run_result_parser(run_result, output_model)
        
        if parsed_result.output.parsed:
            enriched = {
                **row_data,  # Original CSV data
                **parsed_result.output.parsed.model_dump()  # Enriched data
            }
            log(f"  ✓ Successfully enriched row {row_index}")
            return enriched
        else:
            log(f"  ⚠ No parsed output for row {row_index}")
            return None
            
    except Exception as e:
        log(f"  ✗ Error enriching row {row_index}: {str(e)}")
        return None


def save_results_to_csv(results: List[Dict[str, Any]], output_path: str, verbose: bool = True):
    """Save enriched results to CSV."""
    def log(message):
        if verbose:
            print(message)
    
    if not results:
        log("No results to save")
        return
    
    # Get all unique keys across all results
    all_keys = set()
    for result in results:
        all_keys.update(result.keys())
    
    fieldnames = sorted(list(all_keys))
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            # Convert lists to JSON strings for CSV
            row = {}
            for key, value in result.items():
                if isinstance(value, (list, dict)):
                    row[key] = json.dumps(value)
                else:
                    row[key] = value
            writer.writerow(row)
    
    log(f"\n✓ Results saved to: {output_path}")


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def run(
    csv_path: str,
    research_objective: str,
    output_path: Optional[str] = None,
    test_mode: bool = False,
    max_rows: Optional[int] = None,
    save_csv: bool = True,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    Programmable interface for the flexible enrichment pipeline.
    
    Use this function to call the pipeline directly from Python scripts.
    
    Args:
        csv_path: Path to input CSV file
        research_objective: Natural language description of what to research
        output_path: Path for output CSV file (default: /mnt/user-data/outputs/enriched_output.csv)
        test_mode: If True, process only first 3 rows
        max_rows: Maximum number of rows to process (None = all)
        save_csv: If True, save results to CSV (default: True)
        verbose: If True, print progress messages (default: True)
    
    Returns:
        List of dictionaries containing enriched data for each row
        
    Example:
        >>> results = run(
        ...     csv_path="data.csv",
        ...     research_objective="Find product features and pricing",
        ...     test_mode=True
        ... )
        >>> print(f"Enriched {len(results)} companies")
        >>> print(results[0].keys())  # See available fields
    """
    if output_path is None:
        output_path = "/mnt/user-data/outputs/enriched_output.csv"
    
    return run_flexible_pipeline(
        csv_path=csv_path,
        research_objective=research_objective,
        output_path=output_path,
        test_mode=test_mode,
        max_rows=max_rows,
        save_csv=save_csv,
        verbose=verbose
    )


def run_flexible_pipeline(
    csv_path: str,
    research_objective: str,
    output_path: str,
    test_mode: bool = False,
    max_rows: Optional[int] = None,
    save_csv: bool = True,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    Run the flexible enrichment pipeline.
    
    Args:
        csv_path: Path to input CSV file
        research_objective: Natural language description of what to research
        output_path: Path for output CSV file
        test_mode: If True, process only first 3 rows
        max_rows: Maximum number of rows to process (None = all)
        save_csv: If True, save results to CSV
        verbose: If True, print progress messages
        
    Returns:
        List of dictionaries containing enriched data
    """
    def log(message):
        """Print message if verbose mode is on."""
        if verbose:
            print(message)
    
    log("="*80)
    log("FLEXIBLE ENRICHMENT PIPELINE")
    log("="*80)
    
    # Step 1: Analyze CSV structure
    log("\n[1/6] Analyzing CSV structure...")
    csv_structure = analyze_csv_structure(csv_path)
    log(f"  Found {len(csv_structure['columns'])} columns")
    log(f"  Total rows: {csv_structure['total_rows']}")
    log(f"  Columns: {', '.join(csv_structure['columns'])}")
    
    # Step 2: Generate output schema using Claude
    log("\n[2/6] Generating output schema from research objective...")
    log(f"  Research objective: {research_objective}")
    schema_def = generate_output_schema_with_claude(research_objective, csv_structure)
    log(f"  Generated {len(schema_def['fields'])} output fields:")
    for field in schema_def['fields']:
        log(f"    - {field['name']} ({field['type']}): {field['description'][:60]}...")
    
    # Step 3: Create dynamic Pydantic models
    log("\n[3/6] Creating dynamic Pydantic models...")
    input_model = create_dynamic_input_model(csv_structure['columns'])
    output_model = create_dynamic_output_model(schema_def)
    log("  ✓ Input model created")
    log("  ✓ Output model created")
    
    # Step 4: Build task spec
    log("\n[4/6] Building task specification...")
    task_spec = build_task_spec_param(input_model, output_model)
    log("  ✓ Task spec ready")
    
    # Step 5: Initialize Parallel client
    log("\n[5/6] Initializing Parallel API client...")
    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        raise ValueError("PARALLEL_API_KEY environment variable not set")
    client = Parallel(api_key=api_key)
    log("  ✓ Client initialized")
    
    # Step 6: Enrich rows
    log("\n[6/6] Enriching data...")
    rows_to_process = csv_structure['all_rows']
    
    if test_mode:
        rows_to_process = rows_to_process[:3]
        log(f"  TEST MODE: Processing first 3 rows only")
    elif max_rows:
        rows_to_process = rows_to_process[:max_rows]
        log(f"  Processing first {max_rows} rows")
    
    log(f"  Total rows to process: {len(rows_to_process)}")
    log("")
    
    results = []
    
    for idx, row in enumerate(rows_to_process, 1):
        log(f"\n[{idx}/{len(rows_to_process)}] Processing row...")
        
        # Show a preview of the row
        first_col = csv_structure['columns'][0]
        log(f"  {first_col}: {row.get(first_col, 'N/A')}")
        
        enriched = enrich_row(
            client=client,
            row_data=row,
            input_model=input_model,
            output_model=output_model,
            task_spec=task_spec,
            row_index=idx,
            verbose=verbose
        )
        
        if enriched:
            results.append(enriched)
    
    # Save results
    log("\n" + "="*80)
    log("ENRICHMENT COMPLETE")
    log("="*80)
    log(f"Successfully enriched: {len(results)}/{len(rows_to_process)} rows")
    
    if results and save_csv:
        save_results_to_csv(results, output_path, verbose=verbose)
    
    return results


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Main CLI interface."""
    if len(sys.argv) < 3:
        print("""
Flexible Enrichment Pipeline

Usage:
  python flexible_enrichment_pipeline.py <csv_path> <research_objective> [options]

Arguments:
  csv_path            Path to input CSV file
  research_objective  Natural language description of what to research (in quotes)

Options:
  --output PATH       Output CSV path (default: enriched_output.csv)
  --test              Test mode - process only first 3 rows
  --max-rows N        Process maximum N rows

Examples:
  # Test mode with 3 rows
  python flexible_enrichment_pipeline.py data.csv "Find the founding date and employee count" --test
  
  # Full run
  python flexible_enrichment_pipeline.py companies.csv "Research product features, pricing, and target market"
  
  # Process first 10 rows
  python flexible_enrichment_pipeline.py data.csv "Find competitors and market position" --max-rows 10

Environment Variables Required:
  PARALLEL_API_KEY     - Your Parallel.ai API key
  ANTHROPIC_API_KEY    - Your Anthropic API key for schema generation
""")
        sys.exit(1)
    
    # Parse arguments
    csv_path = sys.argv[1]
    research_objective = sys.argv[2]
    
    # Default options
    output_path = "/mnt/user-data/outputs/enriched_output.csv"
    test_mode = False
    max_rows = None
    
    # Parse options
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--output' and i + 1 < len(sys.argv):
            output_path = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--test':
            test_mode = True
            i += 1
        elif sys.argv[i] == '--max-rows' and i + 1 < len(sys.argv):
            max_rows = int(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    
    # Check file exists
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Check API keys
    if not os.environ.get("PARALLEL_API_KEY"):
        print("Error: PARALLEL_API_KEY environment variable not set")
        sys.exit(1)
    
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)
    
    # Run pipeline
    try:
        run_flexible_pipeline(
            csv_path=csv_path,
            research_objective=research_objective,
            output_path=output_path,
            test_mode=test_mode,
            max_rows=max_rows
        )
    except Exception as e:
        print(f"\n✗ Pipeline failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()