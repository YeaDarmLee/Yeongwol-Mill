import os
from PIL import Image, ImageDraw

def create_millstone_favicons():
    # 1. 고해상도 SVG 생성 (전통 맷돌 & 황금 참깨알 디자인)
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#3d2317" />
      <stop offset="100%" stop-color="#1e110a" />
    </linearGradient>
    <linearGradient id="goldGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f5e0a3" />
      <stop offset="100%" stop-color="#c59b27" />
    </linearGradient>
    <linearGradient id="stoneGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6e6259" />
      <stop offset="100%" stop-color="#403731" />
    </linearGradient>
  </defs>

  <!-- 원형 우드/스톤 엠블럼 배경 -->
  <circle cx="32" cy="32" r="30" fill="url(#bgGrad)" stroke="url(#goldGrad)" stroke-width="2.5"/>
  <circle cx="32" cy="32" r="26.5" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="1"/>

  <!-- 전통 맷돌 (Millstone Outer Circle) -->
  <circle cx="32" cy="32" r="17" fill="url(#stoneGrad)" stroke="#c59b27" stroke-width="1.8"/>

  <!-- 맷돌 홈 (Millstone Grooves / Pattern) -->
  <line x1="32" y1="18" x2="32" y2="23" stroke="#26201b" stroke-width="2" stroke-linecap="round"/>
  <line x1="32" y1="41" x2="32" y2="46" stroke="#26201b" stroke-width="2" stroke-linecap="round"/>
  <line x1="18" y1="32" x2="23" y2="32" stroke="#26201b" stroke-width="2" stroke-linecap="round"/>
  <line x1="41" y1="32" x2="46" y2="32" stroke="#26201b" stroke-width="2" stroke-linecap="round"/>

  <!-- 맷돌 구멍 (Center Hole) -->
  <circle cx="32" cy="32" r="4.5" fill="#1e110a" stroke="#c59b27" stroke-width="1.2"/>

  <!-- 맷돌 손잡이 (Millstone Handle / 맷잡이) -->
  <circle cx="43" cy="23" r="3.2" fill="#c59b27"/>
  <circle cx="43" cy="23" r="1.5" fill="#3d2317"/>

  <!-- 황금 참깨알 2개 (Golden Sesame Seeds) -->
  <!-- 참깨 1 (좌측 하단) -->
  <path d="M 12 43 C 10 38, 15 35, 17 40 C 18 43, 14 46, 12 43 Z" fill="#eac775" stroke="#8c6b12" stroke-width="0.8"/>
  <!-- 참깨 2 (우측 상단) -->
  <path d="M 48 16 C 52 14, 53 19, 49 21 C 46 22, 45 18, 48 16 Z" fill="#f3dc98" stroke="#8c6b12" stroke-width="0.8"/>
</svg>"""

    os.makedirs('static/admin', exist_ok=True)

    with open('static/favicon.svg', 'w', encoding='utf-8') as f:
        f.write(svg_content)
    with open('static/admin/favicon.svg', 'w', encoding='utf-8') as f:
        f.write(svg_content)

    # 2. PIL을 이용하여 PNG / ICO 파비콘 생성 (128x128 기반)
    img = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 원형 배경
    draw.ellipse([4, 4, 124, 124], fill='#3d2317', outline='#c59b27', width=5)
    draw.ellipse([10, 10, 118, 118], outline=(255, 255, 255, 40), width=2)

    # 맷돌 외부 (Millstone Outer)
    draw.ellipse([30, 30, 98, 98], fill='#5a4e46', outline='#c59b27', width=4)

    # 맷돌 홈 (Grooves)
    draw.line([(64, 34), (64, 46)], fill='#26201b', width=4)
    draw.line([(64, 82), (64, 94)], fill='#26201b', width=4)
    draw.line([(34, 64), (46, 64)], fill='#26201b', width=4)
    draw.line([(82, 64), (94, 64)], fill='#26201b', width=4)

    # 맷돌 구멍 (Center Hole)
    draw.ellipse([54, 54, 74, 74], fill='#1e110a', outline='#c59b27', width=3)

    # 맷돌 손잡이 (Handle)
    draw.ellipse([84, 42, 98, 56], fill='#c59b27')
    draw.ellipse([88, 46, 94, 52], fill='#3d2317')

    # 황금 참깨알 2개 (Golden Seeds)
    # 참깨 1 (좌측 하단)
    draw.ellipse([20, 80, 36, 94], fill='#eac775', outline='#8c6b12', width=2)
    # 참깨 2 (우측 상단)
    draw.ellipse([92, 28, 108, 42], fill='#f3dc98', outline='#8c6b12', width=2)

    # 저장
    img.save('static/favicon.png', 'PNG')
    img.save('static/admin/favicon.png', 'PNG')
    img.save('static/favicon.ico', format='ICO', sizes=[(32, 32), (64, 64)])
    img.save('static/admin/favicon.ico', format='ICO', sizes=[(32, 32), (64, 64)])

    print("New Millstone & Sesame Seed Favicon generated successfully!")

if __name__ == '__main__':
    create_millstone_favicons()
