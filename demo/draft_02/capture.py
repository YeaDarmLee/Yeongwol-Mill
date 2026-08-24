import asyncio
import os
from playwright.async_api import async_playwright

async def capture_screenshots():
    directory = r"c:\workspace\Yeongwol-Mill\draft_02"
    output_dir = os.path.join(directory, "screenshots")
    os.makedirs(output_dir, exist_ok=True)
    
    files_to_capture = {
        "index.html": "index",
        "brand.html": "brand",
        "process.html": "process",
        "products.html": "products",
        "product-detail.html": "product-detail",
        "cart.html": "cart",
        "login.html": "login"
    }
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # PC Context
        pc_context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        pc_page = await pc_context.new_page()
        
        # Mobile Context
        mo_context = await browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
        mo_page = await mo_context.new_page()
        
        for file, base_name in files_to_capture.items():
            file_path = os.path.join(directory, file)
            if os.path.exists(file_path):
                file_url = f"file:///{file_path.replace('\\', '/')}"
                
                # PC
                print(f"Capturing PC: {file_url}")
                await pc_page.goto(file_url, wait_until="networkidle")
                await pc_page.wait_for_timeout(500)
                await pc_page.screenshot(path=os.path.join(output_dir, f"{base_name}_pc.png"), full_page=True)
                
                # Mobile
                print(f"Capturing Mobile: {file_url}")
                await mo_page.goto(file_url, wait_until="networkidle")
                await mo_page.wait_for_timeout(500)
                await mo_page.screenshot(path=os.path.join(output_dir, f"{base_name}_mo.png"), full_page=True)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_screenshots())
