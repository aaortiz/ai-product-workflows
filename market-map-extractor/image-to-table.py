"""
Image to Table Extraction using Claude API
Extracts company data from landscape reports into structured format
"""

import anthropic
import base64
import json
import csv
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize the Anthropic client
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

def image_to_base64(image_path: str) -> tuple[str, str]:
    """
    Convert image to base64 encoding for Claude API
    Returns: (base64_string, media_type)
    """
    with open(image_path, "rb") as image_file:
        image_data = base64.standard_b64encode(image_file.read()).decode("utf-8")
    
    # Determine media type based on extension
    extension = Path(image_path).suffix.lower()
    media_type_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    media_type = media_type_map.get(extension, 'image/jpeg')
    
    return image_data, media_type


def extract_companies_from_landscape(image_path: str) -> dict:
    """
    Extract structured company data from a landscape report image
    """
    # Convert image to base64
    image_data, media_type = image_to_base64(image_path)
    
    # Create the prompt for extraction
    system_prompt = """"""
#     system_prompt = """You are an expert at extracting structured data from landscape reports and market maps. 
# Your task is to extract company names and their categories from images with perfect accuracy."""

    user_prompt = """Please analyze this landscape report image and extract all companies into a structured format. Determine the number of companies to extract by reading titles or any other context in the image, if available.

ONLY extract companies where the company NAME is clearly readable as text. This includes:
- Standard text/wordmarks (even if stylized)
- Clear letter-based logos where you can read the company name

DO NOT extract:
- Logos that are purely geometric shapes, symbols, or patterns
- Logos where you cannot confidently read actual letters/text
- Decorative elements that might look like text but aren't readable

For each company, identify:
1. Company name (exact spelling as shown - must be readable text)
2. Category/section it belongs to
3. Any visible metadata (if present)

Return the data as a JSON object with this structure:
{
    "report_title": "string",
    "report_date": "string (if visible)",
    "categories": [
        {
            "category_name": "string",
            "companies": ["company1", "company2", ...]
        }
    ]
}

Be extremely careful with company name spelling. If you cannot clearly READ the company name as text letters, skip it rather than guessing."""

#     user_prompt = """Please analyze this landscape report image and extract all companies into a structured format. Determine the number of companies to extract by reading titles or any other context in the image, if available.

# For each company, identify:
# 1. Company name (exact spelling as shown)
# 2. Category/section it belongs to
# 3. Any visible metadata (if present)

# Return the data as a JSON object with this structure:
# {
#     "report_title": "string",
#     "report_date": "string (if visible)",
#     "categories": [
#         {
#             "category_name": "string",
#             "companies": ["company1", "company2", ...]
#         }
#     ]
# }

# Be extremely careful with company name spelling. If you're unsure about a name, include it with a note."""

    # Call Claude API with vision
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",  # Latest model with vision
        max_tokens=4096,
        temperature=0,  # Use 0 for deterministic extraction
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt
                    }
                ],
            }
        ],
    )
    
    # Extract the response
    response_text = message.content[0].text
    
    # Parse JSON from response
    # Claude might wrap JSON in markdown code blocks, so we need to extract it
    if "```json" in response_text:
        json_str = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        json_str = response_text.split("```")[1].split("```")[0].strip()
    else:
        json_str = response_text.strip()
    
    return json.loads(json_str)


def structured_data_to_csv(data: dict, output_path: str):
    """
    Convert structured JSON data to CSV format
    """
    rows = []
    report_title = data.get("report_title", "Unknown Report")
    
    for category in data["categories"]:
        category_name = category["category_name"]
        for company in category["companies"]:
            rows.append({
                "Company Name": company,
                "Category": category_name,
                "Report": report_title
            })
    
    # Write to CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["Company Name", "Category", "Report"])
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"✅ Extracted {len(rows)} companies to {output_path}")
    return rows


def extract_with_validation(image_path: str, output_csv: str = "companies.csv"):
    """
    Main function: Extract companies and validate the output
    """
    print(f"🔍 Analyzing image: {image_path}")
    
    # Extract structured data
    structured_data = extract_companies_from_landscape(image_path)
    
    # Display summary
    print(f"\n📊 Extraction Summary:")
    print(f"Report: {structured_data.get('report_title', 'N/A')}")
    print(f"Categories found: {len(structured_data['categories'])}")
    
    total_companies = sum(len(cat['companies']) for cat in structured_data['categories'])
    print(f"Total companies: {total_companies}\n")
    
    # Show breakdown by category
    for category in structured_data['categories']:
        print(f"  {category['category_name']}: {len(category['companies'])} companies")
    
    # Save to CSV
    rows = structured_data_to_csv(structured_data, output_csv)
    
    return structured_data, rows

# Example usage
if __name__ == "__main__":
    # Extract from the Accel report
    image_path = "market-map-extractor/images/accel-2025-US-AI-100.png"
    
    # Create output directory if it doesn't exist
    output_dir = Path("market-map-extractor/output")
    output_dir.mkdir(exist_ok=True)
    
    # Generate output filenames based on input image
    image_name = Path(image_path).stem
    output_csv = output_dir / f"{image_name}_extracted.csv"
    output_json = output_dir / f"{image_name}_extracted.json"
    
    try:
        structured_data, rows = extract_with_validation(image_path, str(output_csv))
        
        # Save JSON as well
        with open(output_json, "w") as f:
            json.dump(structured_data, f, indent=2)
        
        print("\n✅ Extraction complete!")
        print(f"   - JSON: {output_json}")
        print(f"   - CSV: {output_csv}")
        
    except Exception as e:
        print(f"❌ Error: {e}")