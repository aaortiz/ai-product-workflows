import os
import re
import json
from pprint import pprint
from typing import Union
from pathlib import Path
from kernel import Kernel
from dotenv import load_dotenv

# Load environment variables
repo_root = Path(__file__).parent.parent
load_dotenv(repo_root / '.env')

# Initialize Kernel client
kernel = Kernel()

# Output directory for downloads
DOWNLOAD_DIR = Path(__file__).parent / "downloads" / "favicons-v5"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------
# Static Playwright JS template with placeholders
# ---------------------------------------------------------------------

PLAYWRIGHT_FAVICON_TEMPLATE = r"""
// 🤖 Playwright favicon + description extractor
const companyName = "__COMPANY_NAME__";
const websiteUrl = "__WEBSITE_URL__";

await page.goto(websiteUrl, { waitUntil: "domcontentloaded" });

const baseUrl = new URL(websiteUrl).origin;
const favicons = [];

// Helper: infer type from URL + content-type
function inferTypeFromUrlAndContentType(url, contentType) {
  const lowerUrl = url.toLowerCase();
  const ct = (contentType || "").toLowerCase();

  if (lowerUrl.endsWith(".svg") || ct.includes("svg")) return "svg";
  if (
    lowerUrl.endsWith(".ico") ||
    ct.includes("x-icon") ||
    ct.includes("vnd.microsoft.icon")
  ) return "ico";
  if (lowerUrl.endsWith(".png") || ct.includes("png")) return "png";
  if (
    lowerUrl.endsWith(".jpg") ||
    lowerUrl.endsWith(".jpeg") ||
    ct.includes("jpeg") ||
    ct.includes("jpg")
  ) return "jpg";
  if (lowerUrl.endsWith(".gif") || ct.includes("gif")) return "gif";
  return "unknown";
}

// 1) Collect favicon link tags
const faviconSelectors = [
  'link[rel*="icon"]',
  'link[rel*="apple-touch-icon"]',
  'link[rel*="mask-icon"]',
  'link[rel*="fluid-icon"]'
];

const linkNodes = await page.$$eval(
  faviconSelectors.join(", "),
  (links, baseUrl) => {
    return Array.from(links)
      .map(link => {
        const href = link.getAttribute("href");
        if (!href) return null;

        const absUrl = href.startsWith("http")
          ? href
          : new URL(href, baseUrl).toString();

        return {
          href: absUrl,
          rel: link.rel || null,
          sizes: link.getAttribute("sizes"),
          typeAttr: link.getAttribute("type") || null
        };
      })
      .filter(Boolean);
  },
  baseUrl
);

// 2) Download each favicon, inline SVG text or base64 for binaries
for (const linkInfo of linkNodes) {
  try {
    const faviconUrl = linkInfo.href;
    const response = await page.request.get(faviconUrl);
    if (!response.ok()) continue;

    const contentType = response.headers()["content-type"] || "";
    const type = inferTypeFromUrlAndContentType(faviconUrl, contentType);

    let content;
    let isBinary;

    if (type === "svg") {
      content = await response.text();
      isBinary = false;
    } else {
      const buffer = await response.body();
      content = buffer.toString("base64");
      isBinary = true;
    }

    favicons.push({
      url: faviconUrl,
      content,
      type,
      sizes: linkInfo.sizes,
      rel: linkInfo.rel,
      isBinary
    });
  } catch (error) {
    // Skip failed downloads
  }
}

// 3) Fallback: /favicon.ico if we don't already have it
try {
  const defaultFaviconUrl = new URL("/favicon.ico", baseUrl).toString();
  const response = await page.request.get(defaultFaviconUrl);
  if (response.ok()) {
    const alreadyExists = favicons.some(favicon => favicon.url === defaultFaviconUrl);
    if (!alreadyExists) {
      const contentType = response.headers()["content-type"] || "";
      const type = inferTypeFromUrlAndContentType(defaultFaviconUrl, contentType);

      const buffer = await response.body();
      const content = buffer.toString("base64");

      favicons.push({
        url: defaultFaviconUrl,
        content,
        type: type === "unknown" ? "ico" : type,
        sizes: null,
        rel: "icon",
        isBinary: true
      });
    }
  }
} catch (error) {
  // Skip if default favicon doesn't exist
}

// 4) Try to extract a description
let description = null;
try {
  description = await page.evaluate(() => {
    const get = (selector) => {
      const el = document.querySelector(selector);
      return el && el.content ? el.content.trim() : null;
    };

    return (
      get('meta[name="description"]') ||
      get('meta[property="og:description"]') ||
      get('meta[name="twitter:description"]') ||
      null
    );
  });

  if (description && description.length > 400) {
    description = description.slice(0, 397) + "...";
  }
} catch (error) {
  description = null;
}

return {
  companyName,
  websiteUrl,
  favicons,
  description
};
"""

def make_playwright_favicon_code(website_url: str, company_name: str) -> str:
    """
    Fill in the Playwright JS template with the concrete website URL and company name.
    """
    return (
        PLAYWRIGHT_FAVICON_TEMPLATE
        .replace("__WEBSITE_URL__", website_url)
        .replace("__COMPANY_NAME__", company_name)
    )

# ---------------------------------------------------------------------
# Favicon ranking / selection
# ---------------------------------------------------------------------

def get_priority(favicon):
    """
    Calculate priority for favicon selection.
    Lower number = higher priority.
    Prioritizes: SVG > PNG > ICO, with boost for "icon" in name (not part of "favicon")
    """
    file_type = favicon.get('type', '').lower()
    url = favicon.get('url', '').lower()
    rel = (favicon.get('rel') or '').lower()
    
    # Check if "icon" appears in URL or rel, but NOT as part of "favicon"
    has_icon = bool(
        re.search(r'(?<!fav)icon\b', url) or 
        re.search(r'(?<!fav)icon\b', rel)
    )
    
    # Base priority by file type: SVG > PNG > ICO
    if file_type == 'svg':
        base_priority = 0
    elif file_type == 'png':
        base_priority = 10
    elif file_type == 'ico':
        base_priority = 20
    else:
        base_priority = 30
    
    # Boost priority (lower number = higher priority) if "icon" is in name
    if has_icon:
        base_priority -= 15
    
    return base_priority

# ---------------------------------------------------------------------
# Main execution function
# ---------------------------------------------------------------------

def execute_favicon_download(website_url: str, company_name: str = None) -> dict:
    """
    Execute favicon download using Kernel's Playwright Execution API.

    Args:
        website_url: The website to visit
        company_name: Optional company name

    Returns:
        Execution result with favicon data
    """
    # Extract company name from URL if not provided
    if not company_name:
        from urllib.parse import urlparse
        domain = urlparse(website_url).netloc
        company_name = domain.replace('www.', '').replace('.com', '').replace('.', '_')

    print(f"\n{'='*60}")
    print(f"Downloading favicons for {company_name}")
    print(f"Website: {website_url}")
    print(f"{'='*60}\n")

    # Generate Playwright code from our static template
    print("🤖 Generating Playwright code to find favicons...")
    playwright_code = make_playwright_favicon_code(website_url, company_name)
    # print(f"Generated code (first 500 chars):\n{playwright_code[:500]}...")
    # print(f"Generated code (last 200 chars):\n...{playwright_code[-200:]}\n")

    # Create a browser session
    print("🌐 Creating Kernel browser...")
    kernel_browser = kernel.browsers.create(stealth=True)
    print(f"Browser live view: {kernel_browser.browser_live_view_url}\n")

    try:
        # Execute the generated Playwright code
        print("▶️  Executing favicon download task...")
        response = kernel.browsers.playwright.execute(
            id=kernel_browser.session_id,
            code=playwright_code,
            timeout_sec=120
        )

        if response.success:
            print("✅ Task completed successfully!\n")

            favicons = []
            description = None
            result_obj = response.result

            # Support both: list of favicons OR { favicons, description, ... }
            if isinstance(result_obj, list):
                favicons = result_obj
            elif isinstance(result_obj, dict):
                favicons = result_obj.get("favicons", []) or []
                description = result_obj.get("description")

            if description:
                print(f"📝 Description: {description}\n")

            if favicons and isinstance(favicons, list):
                print(f"📥 Found {len(favicons)} favicon(s)")

                saved_files = []
                favicons_sorted = sorted(favicons, key=get_priority)
                
                # Only process the first (highest priority) favicon
                if favicons_sorted:
                    favicon = favicons_sorted[0]
                    
                    if isinstance(favicon, dict):
                        url = favicon.get('url')
                        content = favicon.get('content')
                        file_type = favicon.get('type', 'ico')
                        sizes = favicon.get('sizes')
                        rel = favicon.get('rel', 'icon')
                        is_binary = favicon.get('isBinary', True)

                        if content:
                            # Create filename - always single file
                            filename = f"{company_name}_favicon.{file_type}"
                            filepath = DOWNLOAD_DIR / filename

                            try:
                                # Save based on whether it's binary or text
                                if is_binary:
                                    import base64
                                    file_content = base64.b64decode(content)
                                    with open(filepath, 'wb') as f:
                                        f.write(file_content)
                                    file_size = len(file_content)
                                else:
                                    with open(filepath, 'w', encoding='utf-8') as f:
                                        f.write(content)
                                    file_size = len(content.encode('utf-8'))

                                saved_files.append(str(filepath))
                                print(f"  ✅ Saved: {filename} ({file_size:,} bytes)")
                                print(f"     URL: {url}")
                                print(f"     Type: {file_type.upper()} {'(binary/base64)' if is_binary else '(text/SVG)'}")
                                if sizes:
                                    print(f"     Sizes: {sizes}")

                            except Exception as e:
                                print(f"  ❌ Error saving {filename}: {e}")
                        else:
                            print(f"  ⚠️  No content in selected favicon")

                print(f"\n✨ Download complete! Saved {len(saved_files)} file(s)")
                print(f"📁 Location: {DOWNLOAD_DIR}")

                return {
                    "success": True,
                    "favicons": favicons,
                    "saved_files": saved_files,
                    "count": len(saved_files),
                    "description": description,
                }
            else:
                print("⚠️  No favicons found or unexpected result format")
                print(f"Result: {response.result}")

                return {
                    "success": True,
                    "favicons": [],
                    "saved_files": [],
                    "count": 0,
                    "result": response.result
                }

        else:
            print(f"❌ Task failed: {response.error}")
            if response.stderr:
                print(f"Error details:\n{response.stderr}")

            return {
                "success": False,
                "error": response.error,
                "stderr": response.stderr
            }

    finally:
        # Clean up browser session
        kernel.browsers.delete_by_id(kernel_browser.session_id)
        print("🧹 Browser session cleaned up")

# ---------------------------------------------------------------------
# Helpers for building tasks from your report JSON
# ---------------------------------------------------------------------

def create_tasks_from_report(report_data: Union[dict, str], task: str) -> list[dict]:
    """
    Transform a report JSON into an array of tasks for each company.
    
    Args:
        report_data: Either a dict or JSON string containing the report data
        task: The task description to apply to each company
        
    Returns:
        List of task dictionaries with 'task', 'url', and 'name' keys
    """
    if isinstance(report_data, str):
        report_data = json.loads(report_data)
    
    tasks = []
    
    for category in report_data.get("categories", []):
        for company in category.get("companies", []):
            tasks.append({
                "task": task,
                "url": company.get("website", ""),
                "name": company.get("name", "").lower()
            })
    
    return tasks

def main():
    """
    Download favicons + descriptions for each company,
    then update the report JSON to include descriptions.
    """

    # --- Load report ---
    task = (
        "Find and download the company logo. If it's an SVG, return the SVG content. "
        "If it's an image, return the image URL."
    )

    report_path = Path("/Users/aaortiz/Documents/source/ai-product-workflows/enriched_companies_full_v4.json")
    report_data = json.loads(report_path.read_text())

    # Create flat list of tasks
    tasks = create_tasks_from_report(report_data, task=task)

    print("\n📄 Loaded report with categories =",
          len(report_data.get("categories", [])))
    print("🔍 Companies found =", len(tasks))

    results = []

    # --- Execute downloads and append descriptions back into report_data ---
    for company_task in tasks:
        company_url = company_task["url"]
        company_name = company_task["name"]

        result = execute_favicon_download(
            website_url=company_url,
            company_name=company_name
        )
        results.append(result)

        # Attach description to the appropriate company node in report_data
        description = result.get("description")

        # Insert description ONLY if structure matches expectations
        for category in report_data.get("categories", []):
            for company in category.get("companies", []):
                if company.get("name", "").lower() == company_name.lower():
                    company["description"] = description
                    break

        print("\n" + "="*60 + "\n")

    # --- Save updated JSON ---
    output_path = (
        Path("/Users/aaortiz/Documents/source/ai-product-workflows/")
        / "enriched_companies_full_v4_with_descriptions.json"
    )
    output_path.write_text(json.dumps(report_data, indent=2))

    # --- Summary ---
    print("\n📋 SUMMARY")
    successful = sum(1 for r in results if r["success"])
    total_files = sum(r.get("count", 0) for r in results)

    print(f"✅ Successful favicon downloads: {successful}/{len(results)}")
    print(f"📥 Total favicons saved: {total_files}")
    print(f"💾 Updated JSON saved to: {output_path}\n")

if __name__ == "__main__":
    main()