# The simplest Kernel browser use to download
# Kernel's official logo from their official website.

import os
import asyncio
from kernel import Kernel
from browser_use import Browser, Agent, ChatAnthropic
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
repo_root = Path(__file__).parent.parent
load_dotenv(repo_root / '.env')

async def main():
    # Initialize Kernel client
    kernel = Kernel()

    # Create a Kernel browser session
    kernel_browser = kernel.browsers.create()

    print(f"Browser session created: {kernel_browser.session_id}")
    print(f"Live view: {kernel_browser.browser_live_view_url}")

    # Create downloads directory
    downloads_dir = Path("./downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # Update your Browser definition to use Kernel's CDP URL
    browser = Browser(
        cdp_url=kernel_browser.cdp_ws_url,
        headless=False,
        window_size={'width': 1024, 'height': 768},
        viewport={'width': 1024, 'height': 768},
        device_scale_factor=1.0,
        downloads_path=str(downloads_dir.absolute()),
        accept_downloads=True,
    )

    # LLM Instance - using ChatAnthropic as specified
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=os.getenv("ANTHROPIC_API_KEY")
    )

    # Updated task with more specific instructions
    agent = Agent(
        task=f"""Navigate to onkernel.com and extract the company logo.

        IMPORTANT: Use the absolute path {downloads_dir.absolute()} for saving files.

        Steps:
        1. Go to https://onkernel.com
        2. Look for the MAIN company logo "Kernel" text in the header (not small icons)
        3. Extract the full logo SVG content using JavaScript - look for the larger text logo
        4. Save it using write_file with filename 'kernellogo.txt' to {downloads_dir.absolute()}
        5. Make sure to use the full path: {downloads_dir.absolute() / 'kernellogo.txt'}

        Note: The file system only supports .txt, .md, .json, .jsonl, .csv, .pdf extensions.
        Save the SVG content as .txt file.
        """,
        llm=llm,
        browser=browser,
        available_file_paths=[str(downloads_dir.absolute())],
    )

    try:
        # Run your automation
        print("\nStarting browser automation...")
        print(f"Files will be saved to: {downloads_dir.absolute()}")
        history = await agent.run()

        print("\n" + "="*60)
        print("AUTOMATION COMPLETED")
        print("="*60)

        # Print results
        print(f"\nFinal result: {history.final_result()}")
        print(f"Task completed successfully: {history.is_done()}")
        print(f"Number of steps: {history.number_of_steps()}")
        print(f"Total duration: {history.total_duration_seconds():.2f}s")

        if history.has_errors():
            print(f"\nErrors encountered: {history.errors()}")

        # Check for downloaded/saved files
        files = list(downloads_dir.glob("*"))
        if files:
            print(f"\nFiles saved to {downloads_dir.absolute()}:")
            for f in files:
                print(f"  - {f.name} ({f.stat().st_size} bytes)")
                # Show first 200 chars of file content
                if f.suffix in ['.txt', '.svg']:
                    content = f.read_text()[:200]
                    print(f"    Preview: {content}...")
        else:
            print(f"\nNo files found in {downloads_dir.absolute()}")

    except Exception as e:
        print(f"\nError during automation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        print("\nCleaning up browser session...")
        kernel.browsers.delete_by_id(kernel_browser.session_id)
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())