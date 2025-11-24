"""
Adaptive Landscape Report Extractor
Works with various report formats: categorized, uncategorized, different layouts
"""

import anthropic
import base64
import json
import csv
import os
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class AdaptiveLandscapeExtractor:
    """
    Extracts companies from landscape reports of various formats
    """
    
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def image_to_base64(self, image_path: str) -> tuple[str, str]:
        """Convert image to base64"""
        with open(image_path, "rb") as image_file:
            image_data = base64.standard_b64encode(image_file.read()).decode("utf-8")
        
        extension = Path(image_path).suffix.lower()
        media_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        return image_data, media_type_map.get(extension, 'image/jpeg')
    
    def extract_companies(self, image_path: str) -> Dict:
        """
        Extract companies from any landscape report format
        Handles: categorized/uncategorized, grid/list layouts, varying counts
        """
        
        # Convert image
        image_data, media_type = self.image_to_base64(image_path)
        
        # Adaptive prompt that works for all formats
        system_prompt = """You are an expert at extracting structured data from landscape reports and market maps. 
Your task is to extract company names from images with perfect accuracy, regardless of the format or layout."""

        user_prompt = """Analyze this landscape/market report image and extract ALL visible companies.

CRITICAL INSTRUCTIONS:
1. Extract EVERY company name visible in the image
2. Look carefully at:
   - Small or faint text
   - Stylized logos (like "iZOTOP", "aclcla", "n8n")
   - Companies in corners or edges
   - Low contrast text
3. For company names, use EXACT spelling as shown (preserve capitalization, spacing, special characters)
4. Count carefully - verify you found all companies before responding

FORMAT DETECTION:
- If companies are organized in categories/sections → group them by category
- If companies are in a simple list (e.g., "unicorns") → use a single "All Companies" category
- If there's metadata (funding, description) → capture it

Return JSON with this structure:
{
    "report_title": "string (exact title from image)",
    "report_type": "categorized" or "list",
    "metadata": {
        "total_companies_claimed": "number if stated in image, otherwise null",
        "additional_info": "any other metadata like funding totals, dates, etc."
    },
    "categories": [
        {
            "category_name": "string (or 'All Companies' if no categories)",
            "company_count": number,
            "companies": [
                {
                    "name": "exact company name",
                    "metadata": "optional: funding, description, or other data if visible"
                }
            ]
        }
    ],
    "total_companies_extracted": number,
    "extraction_notes": "any challenges, unclear names, or formatting issues"
}

QUALITY CHECKS:
- Double-check stylized logos are read correctly
- Verify your count matches any totals stated in the image
- Note any company names you're unsure about"""

        # Call Claude API
        message = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            temperature=0,
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
        
        # Parse response
        response_text = message.content[0].text
        
        # Extract JSON
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()
        
        data = json.loads(json_str)
        
        # Validate and provide feedback
        self._validate_extraction(data, image_path)
        
        return data
    
    def _validate_extraction(self, data: Dict, image_path: str):
        """
        Adaptive validation based on report type and metadata
        """
        extracted_count = data.get('total_companies_extracted', 0)
        claimed_count = data.get('metadata', {}).get('total_companies_claimed')
        report_type = data.get('report_type', 'unknown')
        
        print(f"\n{'='*60}")
        print(f"EXTRACTION RESULTS: {Path(image_path).name}")
        print(f"{'='*60}")
        print(f"Report: {data.get('report_title', 'Unknown')}")
        print(f"Type: {report_type}")
        print(f"Companies extracted: {extracted_count}")
        
        if claimed_count:
            print(f"Expected (from image): {claimed_count}")
            
            # Check if count matches
            if extracted_count == int(claimed_count):
                print("✅ Count matches - extraction likely complete")
            elif extracted_count < int(claimed_count) * 0.95:
                missing = int(claimed_count) - extracted_count
                print(f"⚠️  Missing ~{missing} companies ({extracted_count}/{claimed_count})")
                print("   Recommend: Review extraction for missed companies")
            elif extracted_count > int(claimed_count):
                print(f"⚠️  Found more companies than claimed ({extracted_count} vs {claimed_count})")
                print("   This might be okay (image may have extra companies)")
        else:
            print("ℹ️  No expected count in image - unable to verify completeness")
        
        # Category breakdown
        print(f"\nCategories: {len(data.get('categories', []))}")
        for cat in data.get('categories', []):
            count = cat.get('company_count', len(cat.get('companies', [])))
            print(f"  • {cat['category_name']}: {count} companies")
        
        # Show any notes
        notes = data.get('extraction_notes')
        if notes:
            print(f"\nNotes: {notes}")
        
        print(f"{'='*60}\n")
    
    def to_csv(self, data: Dict, output_path: str, flatten_metadata: bool = True):
        """
        Convert extracted data to CSV
        
        Args:
            data: Extracted data from extract_companies()
            output_path: Where to save CSV
            flatten_metadata: If True, include metadata columns
        """
        
        rows = []
        report_title = data.get('report_title', 'Unknown Report')
        
        for category in data.get('categories', []):
            category_name = category['category_name']
            
            for company in category.get('companies', []):
                # Handle both simple string and object formats
                if isinstance(company, str):
                    company_name = company
                    company_metadata = None
                else:
                    company_name = company.get('name', 'Unknown')
                    company_metadata = company.get('metadata')
                
                row = {
                    'Company Name': company_name,
                    'Category': category_name,
                    'Report': report_title
                }
                
                if flatten_metadata and company_metadata:
                    row['Metadata'] = company_metadata
                
                rows.append(row)
        
        # Write CSV
        if rows:
            fieldnames = list(rows[0].keys())
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            print(f"💾 Saved to: {output_path}")
        
        return rows


def main():
    """
    Example: Extract from various Accel report formats
    """    
    
    # Initialize
    api_key = os.getenv('ANTHROPIC_API_KEY')
    extractor = AdaptiveLandscapeExtractor(api_key=api_key)
    
    # Test with different report types
    test_images = [
        "market-map-extractor/images/accel-2025-US-AI-100.png"          # Categorized, ~100 companies
        # "accel-2025-EU-AI-100.png",         # Categorized, ~100 companies
        # "accel-2025-ai-native-apps.png",    # Categorized, ~40 companies, has funding
        # "accel-2025-US-unicorns.png",       # List format, ~30 companies
        # "accel-2025-EU-IL-unicorns.png",    # List format, ~21 companies
    ]
    
    for image_file in test_images:
        if not Path(image_file).exists():
            print(f"⏭️  Skipping {image_file} (not found)")
            continue
        
        try:
            # Extract
            data = extractor.extract_companies(image_file)
            
            # Save to CSV
            output_csv = image_file.replace('.png', '_extracted.csv')
            extractor.to_csv(data, output_csv)
            
            # Save JSON
            output_json = image_file.replace('.png', '_extracted.json')
            with open(output_json, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"✅ Processed: {image_file}\n")
            
        except Exception as e:
            print(f"❌ Error processing {image_file}: {e}\n")
    
    print("\n🎉 All reports processed!")


if __name__ == "__main__":
    main()