import pprint
from flexible_enrichment_pipeline import generate_output_schema_with_claude, analyze_csv_structure
from dotenv import load_dotenv
from pathlib import Path


# Load environment variables from .env file in repo root
repo_root = Path(__file__).parent.parent.parent
load_dotenv(repo_root / '.env')

if __name__ == "__main__":
    csv_path = "market-map-extractor/enrichment-pipeline/sample-inputs/accel-2025-ai100-companies-ai-infra.csv"
    csv_structure = analyze_csv_structure(csv_path)
    objective = """
    I want to compare key customers, product delivery methods, primary use cases, and pricing models
    """
    output_schema = generate_output_schema_with_claude(objective, csv_structure)
    pprint.pprint(output_schema, indent=4, width=80)