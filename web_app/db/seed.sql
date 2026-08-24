-- Categories Initial Data
INSERT INTO categories (id, name) VALUES 
(1, '선물세트'),
(2, '참기름'),
(3, '들기름'),
(4, '특산품')
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- Products Initial Data (4 Items)
INSERT INTO products (id, category_id, name, price, capacity, description, badge, image_url, stock) VALUES
(1, 1, '들기름 & 들기름 세트', 50000, '180ml x 2병', '건강을 위해 볶지 않고 그대로 압착한 생들기름 2병 구성', 'BEST', 'assets/gift_set.png', 100),
(2, 1, '참기름 & 들기름 세트', 60000, '180ml x 2병', '고소한 참기름과 건강한 들기름을 함께 즐기는 실속 세트', '추천', 'assets/gift_set.png', 100),
(3, 1, '참기름 & 참기름 세트', 70000, '180ml x 2병', '저온 로스팅으로 맑고 진하게 짜낸 프리미엄 참기름 2병 구성', '프리미엄', 'assets/gift_set.png', 100),
(4, 4, '최상급 영월 고춧가루', 30000, '500g', '일교차가 큰 영월에서 자라 태양빛에 말린 빛깔 고운 고춧가루', '특산품', 'assets/product_redpepper.png', 100)
ON DUPLICATE KEY UPDATE 
name=VALUES(name), price=VALUES(price), capacity=VALUES(capacity), description=VALUES(description), badge=VALUES(badge), image_url=VALUES(image_url);
