import asyncio
import os
from pathlib import Path
from kernel import Kernel
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# Load environment variables
repo_root = Path(__file__).parent.parent
load_dotenv(repo_root / '.env')

DOWNLOAD_DIR = "/tmp/logo_downloads"
LOCAL_DOWNLOAD_DIR = str(Path(__file__).parent / "downloads")

kernel = Kernel()


async def download_company_logo(website_url: str, company_name: str = None):
    """
    Download a company's logo from their website.

    Args:
        website_url: The company website URL (e.g., "https://example.com")
        company_name: Optional company name for filename (defaults to domain name)
    """
    # Extract company name from URL if not provided
    if not company_name:
        from urllib.parse import urlparse
        domain = urlparse(website_url).netloc
        company_name = domain.replace('www.', '').replace('.com', '').replace('.', '_')

    kernel_browser = kernel.browsers.create()
    print(f"Kernel browser live view url: {kernel_browser.browser_live_view_url}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(kernel_browser.cdp_ws_url)
        context = browser.contexts[0]
        page = context.pages[0] if len(context.pages) > 0 else await context.new_page()

        # Set up CDP session for downloads
        cdp_session = await context.new_cdp_session(page)
        await cdp_session.send(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": DOWNLOAD_DIR,
                "eventsEnabled": True,
            },
        )

        download_completed = asyncio.Event()
        download_filename: str | None = None

        def _on_download_begin(event):
            nonlocal download_filename
            download_filename = event.get("suggestedFilename", "unknown")
            print(f"Download started: {download_filename}")

        def _on_download_progress(event):
            if event.get("state") in ["completed", "canceled"]:
                download_completed.set()

        cdp_session.on("Browser.downloadWillBegin", _on_download_begin)
        cdp_session.on("Browser.downloadProgress", _on_download_progress)

        try:
            print(f"Navigating to {website_url}")
            await page.goto(website_url, wait_until="networkidle", timeout=30000)

            # Strategy 1: Try to find logo in common locations
            logo_selectors = [
                # SVG logos in header
                'header svg',
                'header [class*="logo"] svg',
                '.header svg',
                '.navbar svg',

                # Image logos
                'header img[alt*="logo" i]',
                'header img[alt*="brand" i]',
                'header img.logo',
                'header [class*="logo"] img',
                '.logo img',
                '.brand img',

                # Link containing logo
                'header a[href="/"] img',
                'nav a[href="/"] img',

                # Fallback: any image in header
                'header img:first-of-type',
            ]

            logo_element = None
            used_selector = None

            for selector in logo_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        logo_element = element
                        used_selector = selector
                        print(f"Found logo using selector: {selector}")
                        break
                except:
                    continue

            if not logo_element:
                print("Warning: Could not find logo element, trying fallback...")
                # Last resort: look for any prominent image
                logo_element = page.locator('img').first
                used_selector = 'img (fallback)'

            # Determine logo type and extract
            tag_name = await logo_element.evaluate('el => el.tagName.toLowerCase()')
            print(f"Logo element type: {tag_name}")

            local_path = None

            if tag_name == 'svg':
                # Extract SVG content directly
                svg_content = await logo_element.evaluate('el => el.outerHTML')
                filename = f"{company_name}_logo.svg"
                local_path = f"{LOCAL_DOWNLOAD_DIR}/{filename}"
                os.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)

                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(svg_content)
                print(f"Saved SVG logo to {local_path}")

            elif tag_name == 'img':
                # Get image source URL
                img_src = await logo_element.get_attribute('src')

                if img_src:
                    # Handle relative URLs
                    if img_src.startswith('//'):
                        img_src = 'https:' + img_src
                    elif img_src.startswith('/'):
                        from urllib.parse import urljoin
                        img_src = urljoin(website_url, img_src)

                    print(f"Logo image URL: {img_src}")

                    # Check if it's an SVG URL or data URI
                    if img_src.endswith('.svg') or 'image/svg' in img_src:
                        # Navigate to SVG and download
                        response = await page.request.get(img_src)
                        if response.ok:
                            svg_content = await response.text()
                            filename = f"{company_name}_logo.svg"
                            local_path = f"{LOCAL_DOWNLOAD_DIR}/{filename}"
                            os.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)

                            with open(local_path, 'w', encoding='utf-8') as f:
                                f.write(svg_content)
                            print(f"Downloaded SVG logo to {local_path}")
                    else:
                        # Take a screenshot of the logo element
                        filename = f"{company_name}_logo.png"
                        local_path = f"{LOCAL_DOWNLOAD_DIR}/{filename}"
                        os.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)

                        await logo_element.screenshot(path=local_path)
                        print(f"Saved logo screenshot to {local_path}")

                        # Also try to download the original image
                        try:
                            response = await page.request.get(img_src)
                            if response.ok:
                                # Determine file extension from content-type or URL
                                content_type = response.headers.get('content-type', '')
                                ext = '.png'
                                if 'jpeg' in content_type or img_src.endswith('.jpg') or img_src.endswith('.jpeg'):
                                    ext = '.jpg'
                                elif 'png' in content_type or img_src.endswith('.png'):
                                    ext = '.png'
                                elif 'webp' in content_type or img_src.endswith('.webp'):
                                    ext = '.webp'

                                original_filename = f"{company_name}_logo_original{ext}"
                                original_path = f"{LOCAL_DOWNLOAD_DIR}/{original_filename}"

                                content = await response.body()
                                with open(original_path, 'wb') as f:
                                    f.write(content)
                                print(f"Downloaded original image to {original_path}")
                        except Exception as e:
                            print(f"Could not download original image: {e}")

            # Additional info
            if local_path:
                file_size = os.path.getsize(local_path)
                print(f"\nSuccess! Logo downloaded:")
                print(f"  File: {local_path}")
                print(f"  Size: {file_size:,} bytes")
                print(f"  Selector used: {used_selector}")

        except Exception as e:
            print(f"Error downloading logo: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()
            kernel.browsers.delete_by_id(kernel_browser.session_id)
            print("Browser session cleaned up")


async def main():
    """
    Example usage: Download logos from multiple companies
    """
    companies = [
        {"url": "https://onkernel.com", "name": "kernel"},
        # Add more companies here
        # {"url": "https://anthropic.com", "name": "anthropic"},
        # {"url": "https://stripe.com", "name": "stripe"},
    ]

    for company in companies:
        print(f"\n{'='*60}")
        print(f"Downloading logo for {company['name']}")
        print(f"{'='*60}")
        await download_company_logo(company["url"], company["name"])
        print()


if __name__ == "__main__":
    # You can also run it directly with a specific URL:
    # asyncio.run(download_company_logo("https://onkernel.com", "kernel"))

    # Or use the main function to download multiple logos:
    asyncio.run(main())