import os
from pathlib import Path
from kernel import Kernel
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables
repo_root = Path(__file__).parent.parent
load_dotenv(repo_root / '.env')

# Initialize clients
kernel = Kernel()
anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Output directory for downloads
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)


def generate_playwright_code(task: str, website_url: str, company_name: str = None) -> str:
    """
    Use Claude to generate Playwright code based on natural language task.

    Args:
        task: Natural language description of what to do (e.g., "download the company logo")
        website_url: The website URL to visit
        company_name: Optional company name for file naming

    Returns:
        Generated Playwright/TypeScript code
    """
    # Extract company name from URL if not provided
    if not company_name:
        from urllib.parse import urlparse
        domain = urlparse(website_url).netloc
        company_name = domain.replace('www.', '').replace('.com', '').replace('.', '_')

    prompt = f"""You are an expert at writing Playwright automation code. Generate pure JavaScript code to accomplish the following task:

Task: {task}
Website URL: {website_url}
Company Name: {company_name}

CRITICAL REQUIREMENTS:
1. The code will run with access to a `page` object (already initialized Playwright page)
2. Use async/await syntax
3. Navigate to the website using await page.goto('{website_url}')
4. For downloading logos - **IMPORTANT STRATEGY ORDER**:

   a. **FIRST ATTEMPT - Check header for complete logo**:
      - Look in 'header', 'nav', or '[role="banner"]' for logo containers
      - Common container selectors: 'header a[href="/"]', 'header .logo', 'nav .brand', '.header-logo'
      - Check if the container has:
        * A single SVG with <text> elements (best case - complete logo in one element)
        * An image with alt text containing the company name
        * Multiple child elements (e.g., icon SVG + text SVG, or img + span)

   b. **ANALYZE the logo composition**:
      - If you find a container with MULTIPLE logo elements (e.g., two SVGs side-by-side for icon + text):
        * Check if you can capture the parent <a> or <div> that wraps both elements
        * Extract the parent container's outerHTML to get both icon and text together
        * If the parent is too large/complex, note that this is a multi-element logo
      - If you find a SINGLE element with both icon and text content:
        * Extract its outerHTML directly
      - If you only find icon-only elements (no text):
        * Mark this as incomplete and proceed to brand assets page

   c. **FALLBACK - Brand assets page (use when header has fragmented/icon-only logos)**:
      - Look for navigation links or footer links containing: "brand", "press", "media", "assets", "resources", "kit", "guidelines"
      - Navigate to the brand/press page
      - Search for downloadable logos, looking for:
        * Links to image files (.svg, .png, .jpg) with "logo" in the filename or alt text
        * Download buttons or links near "logo" text
        * Preview images showing complete logos with both icon and text
      - Prefer SVG format when available, then PNG/high-res images
      - Extract the download URL or image src

   d. **Extract and return**:
      - Return a structured object with:
        * type: 'svg' | 'image' | 'container' | 'url'
        * content: The outerHTML (for SVG/container) or null
        * url: Image URL (for downloadable images) or null
        * source: 'header' | 'brand-page' to indicate where it was found
        * hasText: boolean indicating if text content is present
        * composition: 'single' | 'multi-element' | 'icon-only'

5. **Decision logic**: Prefer header logos IF they contain text. If header only has icon-only logos, go straight to brand assets page.
6. Handle errors gracefully with try-catch blocks
7. **CRITICAL**: Use ONLY pure JavaScript - ABSOLUTELY NO TypeScript type annotations
   - NO (page: any), (el: Element), (el: any), etc.
   - Just use (page), (el), etc.
   - This code will be executed as JavaScript, not TypeScript

Output ONLY pure JavaScript code, no explanations, no markdown. Start directly with the code.

WRONG: await element.evaluate((el: Element) => el.tagName)
CORRECT: await element.evaluate(el => el.tagName)
"""

    response = anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    code = response.content[0].text.strip()

    # Remove markdown code blocks if present
    if code.startswith('```'):
        lines = code.split('\n')
        code = '\n'.join(lines[1:-1]) if len(lines) > 2 else code

    return code


def execute_browser_task(task: str, website_url: str, company_name: str = None) -> dict:
    """
    Execute a natural language browser task using Kernel's Playwright Execution API.

    Args:
        task: Natural language description (e.g., "download the company logo")
        website_url: The website to visit
        company_name: Optional company name

    Returns:
        Execution result with data and replay URL
    """
    print(f"\n{'='*60}")
    print(f"Task: {task}")
    print(f"Website: {website_url}")
    print(f"{'='*60}\n")

    # Generate Playwright code using LLM
    print("🤖 Generating Playwright code...")
    playwright_code = generate_playwright_code(task, website_url, company_name)
    print(f"Generated code:\n{playwright_code}\n")

    # Create a browser session
    print("🌐 Creating Kernel browser...")
    kernel_browser = kernel.browsers.create(stealth=True)
    print(f"Browser live view: {kernel_browser.browser_live_view_url}\n")

    try:
        # Execute the generated Playwright code
        print("▶️  Executing task...")
        response = kernel.browsers.playwright.execute(
            id=kernel_browser.session_id,
            code=playwright_code,
            timeout_sec=120
        )

        if response.success:
            print("✅ Task completed successfully!\n")

            # Save any downloaded content
            if response.result:
                result = response.result

                # If we got logo content, save it
                if isinstance(result, dict):
                    # Save SVG/HTML content if it exists (handle different key names)
                    logo_type = result.get('logoType') or result.get('type')
                    content = result.get('content') or result.get('logoContent') or result.get('svg_content')

                    # Determine file extension based on type
                    if content and logo_type in ['svg', 'container']:
                        ext = 'svg' if logo_type == 'svg' else 'html'
                        filename = f"{company_name or 'logo'}.{ext}"
                        filepath = DOWNLOAD_DIR / filename
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        print(f"\n💾 Saved {logo_type} logo: {filepath}")

                    if 'image_url' in result or 'url' in result:
                        img_url = result.get('image_url') or result.get('url')
                        print(f"🖼️  Image URL: {img_url}")

                    # Print metadata about the logo
                    metadata_keys = ['source', 'hasText', 'composition']
                    for key in metadata_keys:
                        if key in result:
                            print(f"📊 {key}: {result[key]}")

                    # Print any other returned data
                    for key, value in result.items():
                        if key not in ['svg_content', 'image_url', 'content', 'innerContent', 'logoContent', 'type', 'logoType', 'url'] + metadata_keys:
                            print(f"📊 {key}: {value}")

            # Check if replay_url exists
            replay_url = getattr(response, 'replay_url', None)
            if replay_url:
                print(f"\n🎥 Replay URL: {replay_url}")

            return {
                "success": True,
                "result": response.result,
                "replay_url": replay_url
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


def main():
    """
    Example usage with natural language tasks
    """
    # Example 1: Download a company logo
    tasks = [
        {
            "task": "Find and download the company logo. If it's an SVG, return the SVG content. If it's an image, return the image URL.",
            "url": "https://onkernel.com",
            "name": "kernel"
        },
        # Add more tasks here:
        # {
        #     "task": "Extract the company's main headline and description from the homepage",
        #     "url": "https://anthropic.com",
        #     "name": "anthropic"
        # },
        # {
        #     "task": "Find and extract pricing information",
        #     "url": "https://stripe.com/pricing",
        #     "name": "stripe"
        # },
    ]

    results = []
    for task_config in tasks:
        result = execute_browser_task(
            task=task_config["task"],
            website_url=task_config["url"],
            company_name=task_config.get("name")
        )
        results.append(result)
        print("\n" + "="*60 + "\n")

    # Summary
    print("\n📋 Summary:")
    successful = sum(1 for r in results if r["success"])
    print(f"✅ Successful: {successful}/{len(results)}")
    print(f"❌ Failed: {len(results) - successful}/{len(results)}")


if __name__ == "__main__":
    main()
