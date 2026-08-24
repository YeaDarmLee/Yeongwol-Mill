import os
import time
from playwright.sync_api import sync_playwright

output_dir = r"C:\Users\gnswp\.gemini\antigravity\brain\ff1d15be-a883-417e-9502-c0314536b9bb"
base_dir = os.path.abspath(r"c:\workspace\Yeongwol-Mill\draft_01")

pages_to_capture = ['category.html', 'product.html', 'cart.html']

def take_screenshots():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # 1. Desktop Viewport
        context_desktop = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page_desk = context_desktop.new_page()
        
        for page_name in pages_to_capture:
            file_path = f"file:///{base_dir}/{page_name}".replace('\\', '/')
            print(f"Capturing Desktop: {page_name}")
            page_desk.goto(file_path, wait_until='networkidle')
            time.sleep(1) # Extra wait for animations
            out_path = os.path.join(output_dir, f"{page_name.split('.')[0]}_pc.png")
            page_desk.screenshot(path=out_path, full_page=True)
            print(f"Saved: {out_path}")
            
        context_desktop.close()
        
        # 2. Mobile Viewport (iPhone 13 Mini)
        context_mobile = browser.new_context(viewport={'width': 375, 'height': 812}, has_touch=True, is_mobile=True)
        page_mob = context_mobile.new_page()
        
        for page_name in pages_to_capture:
            file_path = f"file:///{base_dir}/{page_name}".replace('\\', '/')
            print(f"Capturing Mobile: {page_name}")
            page_mob.goto(file_path, wait_until='networkidle')
            time.sleep(1)
            out_path = os.path.join(output_dir, f"{page_name.split('.')[0]}_mo.png")
            page_mob.screenshot(path=out_path, full_page=True)
            print(f"Saved: {out_path}")
            
        context_mobile.close()
        browser.close()

if __name__ == "__main__":
    take_screenshots()
