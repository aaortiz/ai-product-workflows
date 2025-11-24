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
DOWNLOAD_DIR = Path(__file__).parent / "downloads" / "favicons"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def generate_favicon_playwright_code(website_url: str, company_name: str) -> str:
    """
    Use Claude to generate Playwright code to download favicons.

    Args:
        website_url: The website URL to visit
        company_name: Company name for file naming

    Returns:
        Generated Playwright JavaScript code
    """
    prompt = f"""You are an expert at writing Playwright automation code. Generate pure JavaScript code to download a website's favicon (the logo that appears in the browser tab).

Website URL: {website_url}
Company Name: {company_name}

TASK: Find and download ALL favicons from the website. Favicons can be found in multiple ways:

1. **Link tags in HTML** - Check for these rel attributes:
   - rel="icon"
   - rel="shortcut icon"
   - rel="apple-touch-icon"
   - rel="apple-touch-icon-precomposed"
   - rel="mask-icon"
   - rel="fluid-icon"

2. **Default location** - Check /favicon.ico

3. **Extract information**:
   - Get the href/src URL
   - Get the sizes attribute if available
   - Get the rel type
   - Download the actual file content using page.request.get()

4. **Content encoding - VERY IMPORTANT**:
   - For SVG files (.svg or content-type contains 'svg'): return as TEXT using response.text()
   - For binary files (ico, png, jpg, etc.): return as base64 using (await response.body()).toString('base64')

5. **Return format**: Return an array of favicon objects, each containing:
   - url: the favicon URL
   - content: the file content (TEXT for SVG, base64 string for binary files)
   - type: file type (svg, ico, png, etc.)
   - sizes: sizes attribute if available
   - rel: the rel attribute value
   - isBinary: true for binary files (ico, png, jpg), false for SVG

CRITICAL REQUIREMENTS:
- Use ONLY pure JavaScript - ABSOLUTELY NO TypeScript type annotations
- NO (page: any), (el: Element), etc. - just use (page), (el)
- NO require() or import statements - the `page` object is already available
- DO NOT create a new browser or page - use the provided `page` object
- Use async/await syntax
- Navigate to {website_url} first using: await page.goto('{website_url}')
- Use page.request.get() to download favicon files
- Convert binary content to base64 using .toString('base64')
- Handle both absolute and relative URLs (use new URL(href, baseUrl) for relative URLs)
- Return an array of favicon objects, even if only one is found

Output ONLY pure JavaScript code, no explanations, no markdown.

EXAMPLE structure to return:
return [
  {{
    url: "https://example.com/favicon.ico",
    content: "base64_encoded_content_here",
    type: "ico",
    sizes: null,
    rel: "icon"
  }},
  // ... more favicons
];

CRITICAL: The code MUST end with a return statement that returns the array of favicons.
If no favicons are found, return an empty array: return [];
"""

    response = anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    code = response.content[0].text.strip()

    # Remove markdown code blocks if present
    if code.startswith('```'):
        lines = code.split('\n')
        code = '\n'.join(lines[1:-1]) if len(lines) > 2 else code

    # Ensure code has a return statement
    code_lines = code.strip().split('\n')
    last_lines = '\n'.join(code_lines[-10:]).lower()

    if 'return' not in last_lines:
        code += '\n\nreturn favicons;'

    # Check if code is already wrapped in IIFE or has function invocation
    code_lower = code.lower()
    has_iife = code_lower.strip().startswith('(async')
    has_already_called = 'await ' in code_lower and '(page)' in code_lower and code_lower.rfind('await') > code_lower.rfind('async function')

    if has_iife or has_already_called:
        # Already has proper invocation, just return
        return code

    # Extract function name and add invocation
    import re
    function_match = re.search(r'async function (\w+)\s*\(', code)

    if function_match:
        function_name = function_match.group(1)
        code += f'\n\nconst result = await {function_name}(page);\nreturn result;'
    else:
        # No function found - code might be inline, just ensure it returns
        if 'return' not in code_lines[-5:]:
            code += '\n\nreturn favicons;'

    return code


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

    # Generate Playwright code using LLM
    print("🤖 Generating Playwright code to find favicons...")
    playwright_code = generate_favicon_playwright_code(website_url, company_name)
    print(f"Generated code (first 500 chars):\n{playwright_code[:500]}...")
    print(f"Generated code (last 200 chars):\n...{playwright_code[-200:]}\n")

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

            if response.result and isinstance(response.result, list):
                favicons = response.result
                print(f"📥 Found {len(favicons)} favicon(s)")

                saved_files = []

                for idx, favicon in enumerate(favicons):
                    if not isinstance(favicon, dict):
                        continue

                    url = favicon.get('url')
                    content = favicon.get('content')
                    file_type = favicon.get('type', 'ico')
                    sizes = favicon.get('sizes')
                    rel = favicon.get('rel', 'icon')
                    is_binary = favicon.get('isBinary', True)

                    if not content:
                        print(f"  ⚠️  Skipping favicon {idx + 1}: no content")
                        continue

                    # Create filename
                    if len(favicons) > 1:
                        size_str = f"_{sizes.replace(' ', '_')}" if sizes else ''
                        rel_str = rel.replace(' ', '_').replace('-', '_')
                        filename = f"{company_name}_favicon_{rel_str}{size_str}.{file_type}"
                    else:
                        filename = f"{company_name}_favicon.{file_type}"

                    filepath = DOWNLOAD_DIR / filename

                    try:
                        # Save based on whether it's binary or text
                        if is_binary:
                            # Decode base64 content and save as binary
                            import base64
                            file_content = base64.b64decode(content)
                            with open(filepath, 'wb') as f:
                                f.write(file_content)
                            file_size = len(file_content)
                        else:
                            # Save as text (SVG)
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(content)
                            file_size = len(content.encode('utf-8'))

                        saved_files.append(str(filepath))
                        print(f"  ✅ Saved: {filename} ({file_size:,} bytes)")
                        print(f"     URL: {url}")
                        print(f"     Type: {'binary (base64)' if is_binary else 'text (SVG)'}")
                        if sizes:
                            print(f"     Sizes: {sizes}")

                    except Exception as e:
                        print(f"  ❌ Error saving {filename}: {e}")

                print(f"\n✨ Download complete! Saved {len(saved_files)} file(s)")
                print(f"📁 Location: {DOWNLOAD_DIR}")

                return {
                    "success": True,
                    "favicons": favicons,
                    "saved_files": saved_files,
                    "count": len(saved_files)
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


def main():
    """
    Example usage: Download favicons from multiple companies
    """
    companies = [
        {"url": "https://onkernel.com", "name": "kernel"},
        {"url": "https://anthropic.com", "name": "anthropic"},
        # Add more companies here
        # {"url": "https://stripe.com", "name": "stripe"},
        # {"url": "https://github.com", "name": "github"},
        # {"url": "https://openai.com", "name": "openai"},
    ]

    results = []
    for company in companies:
        result = execute_favicon_download(
            website_url=company["url"],
            company_name=company.get("name")
        )
        results.append(result)
        print("\n" + "="*60 + "\n")

    # Summary
    print("\n📋 Summary:")
    successful = sum(1 for r in results if r["success"])
    total_files = sum(r.get("count", 0) for r in results)
    print(f"✅ Successful: {successful}/{len(results)}")
    print(f"📥 Total favicons downloaded: {total_files}")


if __name__ == "__main__":
    main()