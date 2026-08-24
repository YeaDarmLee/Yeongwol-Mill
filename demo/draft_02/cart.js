// 장바구니 개수 업데이트
function updateCartCount() {
    const cart = JSON.parse(localStorage.getItem('yw_cart')) || [];
    let totalCount = 0;
    cart.forEach(item => {
        totalCount += item.quantity;
    });
    
    // 헤더 장바구니 숫자 업데이트
    const cartNavs = document.querySelectorAll('a[href*="cart.html"]');
    cartNavs.forEach(nav => {
        if(nav.innerText.includes('장바구니')) {
            if (totalCount > 0) {
                nav.innerHTML = `장바구니 <span class="cart-badge">${totalCount}</span>`;
            } else {
                nav.innerHTML = `장바구니`;
            }
        }
    });
}

// 장바구니에 아이템 추가
function addToCart(item) {
    let cart = JSON.parse(localStorage.getItem('yw_cart')) || [];
    
    // 동일한 옵션의 상품이 있는지 확인
    const existingItemIndex = cart.findIndex(cartItem => 
        cartItem.id === item.id && cartItem.option === item.option
    );

    if (existingItemIndex > -1) {
        cart[existingItemIndex].quantity += item.quantity;
    } else {
        cart.push(item);
    }

    localStorage.setItem('yw_cart', JSON.stringify(cart));
    updateCartCount();
    
    if (confirm('장바구니에 상품이 담겼습니다. 장바구니로 이동하시겠습니까?')) {
        window.location.href = 'cart.html';
    }
}

// DOM 로드 시 장바구니 수량 렌더링
document.addEventListener('DOMContentLoaded', () => {
    updateCartCount();
});
