
import sys
import os
import time
from playwright.sync_api import sync_playwright

def take_screenshot(url, output_path):
    print(f"Taking screenshot of {url} to {output_path}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle")
            # Wait for content to render
            page.wait_for_timeout(2000)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            page.screenshot(path=output_path, full_page=True)
            print("Screenshot saved.")
        except Exception as e:
            print(f"Error taking screenshot: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        # Default for testing
        url = "http://localhost:5173" 
        out = "screenshot.png"
        if len(sys.argv) > 1: url = sys.argv[1]
        
        take_screenshot(url, out)
    else:
        take_screenshot(sys.argv[1], sys.argv[2])
