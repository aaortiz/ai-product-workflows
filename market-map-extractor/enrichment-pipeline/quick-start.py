"""
Quickstart: Simplest Possible Usage

This is the absolute simplest way to use the flexible pipeline.
"""

import os
import csv
from flexible_enrichment_pipeline import run
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file in repo root
repo_root = Path(__file__).parent.parent.parent
load_dotenv(repo_root / '.env')

# Create a quick test CSV
test_data = [
    {'company_name': 'Stripe', 'website': 'stripe.com'},
    {'company_name': 'Plaid', 'website': 'plaid.com'},
]

with open('quickstart_data.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['company_name', 'website'])
    writer.writeheader()
    writer.writerows(test_data)

# Set your API keys first!
# export PARALLEL_API_KEY='your-key'
# export ANTHROPIC_API_KEY='your-key'

# Run the pipeline - that's it!
results = run(
    csv_path='quickstart_data.csv',
    research_objective="Find the founding year and number of employees",
    output_path="market-map-extractor/enrichment-pipeline/sample-outputs/enriched_quickstart_output.csv",
    test_mode=True
)

# Access your enriched data
print("\n" + "="*60)
print("YOUR ENRICHED DATA")
print("="*60 + "\n")

for company in results:
    print(f"Company: {company.get('company_name')}")
    print(f"Fields: {', '.join(company.keys())}")
    print()