-- Initial Seed Data for 영월고향방앗간 (v2.2 Gold Master)

INSERT IGNORE INTO categories (id, name) VALUES 
(1, '참기름'),
(2, '들기름'),
(3, '고춧가루'),
(4, '선물세트');

-- Products
INSERT IGNORE INTO products (
    id, category_id, name, price, capacity, description, badge, image_url, is_active,
    shelf_life_text, origin_info, food_type, contents_capacity, raw_ingredients, manufacturer, storage_method, allergy_notice, nutrition_facts, cs_phone
) VALUES 
(
    1, 1, '전통 저온착유 참기름 300ml', 25000, '300ml', 
    '강원도 영월의 깨끗한 풍토에서 재배한 국산 통참깨 100%를 저온에서 은은하게 볶아 짜낸 명품 참기름입니다.', 
    'BEST', 'assets/product_sesame.png', 1,
    '제조일로부터 12개월', '참깨: 국산(강원도 영월군 100%)', '식용유지류 (참기름)', '300ml',
    '국산 참깨 100%', '영월고향방앗간', '직사광선을 피하고 서늘한 곳에 보관', '참깨 함유', '100ml당 884kcal', '033-000-0000'
),
(
    2, 2, '생 들기름 300ml', 28000, '300ml', 
    '볶지 않고 착유하여 오메가-3 생영양소를 그대로 살린 100% 국산 생 들기름입니다.', 
    'NEW', 'assets/product_sesame.png', 1,
    '제조일로부터 6개월', '들깨: 국산(강원도 영월군 100%)', '식용유지류 (생들기름)', '300ml',
    '국산 들깨 100%', '영월고향방앗간', '개봉 후 냉장보관 권장', '들깨 함유', '100ml당 884kcal', '033-000-0000'
),
(
    3, 3, '영월 태양초 고춧가루 500g', 32000, '500g', 
    '영월의 비옥한 토양에서 태양빛을 한껏 머금고 자란 국산 태양초 고추만을 빻아 만든 깔끔하게 매운 고춧가루입니다.', 
    'HOT', 'assets/product_redpepper.png', 1,
    '제조일로부터 12개월', '고추: 국산(강원도 영월군 100%)', '고춧가루', '500g',
    '국산 건고추 100%', '영월고향방앗간', '밀봉 후 냉동 보관 추천', '해당없음', '100g당 300kcal', '033-000-0000'
),
(
    4, 4, '영월고향방앗간 프리미엄 선물세트 (참기름+들기름)', 55000, '참기름 300ml + 들기름 300ml', 
    '소중한 분께 감사의 마음을 전하는 전통 한지 포장의 프리미엄 전통기름 2종 세트입니다.', 
    'GIFT', 'assets/gift_set.png', 1,
    '제조일로부터 6~12개월', '참깨: 국산 100%, 들깨: 국산 100%', '식용유지류', '300ml x 2병',
    '국산 참깨 100%, 국산 들깨 100%', '영월고향방앗간', '서늘한 곳 보관', '참깨, 들깨 함유', '100ml당 884kcal', '033-000-0000'
);

-- Product Options (Single Source of Truth for Inventory)
INSERT IGNORE INTO product_options (id, product_id, option_name, additional_price, stock, reserved_stock) VALUES
(1, 1, '300ml (기본)', 0, 100, 0),
(2, 1, '500ml (+15,000원)', 15000, 50, 0),
(3, 2, '300ml (기본)', 0, 100, 0),
(4, 2, '500ml (+17,000원)', 17000, 40, 0),
(5, 3, '500g 보통맛', 0, 200, 0),
(6, 3, '500g 매운맛 (+1,000원)', 1000, 150, 0),
(7, 4, '기본 세트 (참기름300ml+들기름300ml)', 0, 80, 0);

-- Remote Area Shipping Rules (Jeju & Island prefixes)
INSERT IGNORE INTO remote_shipping_rules (id, postal_code_prefix, region_name, surcharge) VALUES
(1, '63', '제주특별자치도', 3000),
(2, '231', '인천 옹진군 섬지역', 3000),
(3, '402', '전남 신안군 섬지역', 3000),
(4, '540', '경북 울릉군', 5000);
