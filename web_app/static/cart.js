// 영월고향방앗간 공통 스크립트 (장바구니 & JWT 로그인 상태 관리)

function updateCartCount() {
    const cart = JSON.parse(localStorage.getItem('yw_cart')) || [];
    let totalCount = 0;
    cart.forEach(item => {
        totalCount += item.quantity;
    });
    
    const cartNavs = document.querySelectorAll('a[href*="cart.html"], #cart-nav');
    cartNavs.forEach(nav => {
        if(nav.innerText.includes('장바구니') || nav.id === 'cart-nav') {
            if (totalCount > 0) {
                nav.innerHTML = `장바구니 <span class="cart-badge">${totalCount}</span>`;
            } else {
                nav.innerHTML = `장바구니 (0)`;
            }
        }
    });
}

function addToCart(item, redirect = true) {
    let cart = JSON.parse(localStorage.getItem('yw_cart')) || [];
    
    const existingItemIndex = cart.findIndex(cartItem => 
        cartItem.id === item.id && cartItem.capacity === item.capacity
    );

    if (existingItemIndex > -1) {
        cart[existingItemIndex].quantity += item.quantity;
    } else {
        cart.push(item);
    }

    localStorage.setItem('yw_cart', JSON.stringify(cart));
    updateCartCount();
    
    if (redirect) {
        if (confirm('장바구니에 상품이 담겼습니다. 장바구니로 이동하시겠습니까?')) {
            window.location.href = 'cart.html';
        }
    }
}

// 사용자 JWT 및 헤더 유틸리티 처리
function updateHeaderAuthUI() {
    const token = localStorage.getItem('yw_jwt_token');
    const user = JSON.parse(localStorage.getItem('yw_user') || 'null');
    
    const utilityDiv = document.querySelector('.utility');
    if (!utilityDiv) return;

    if (token && user) {
        utilityDiv.innerHTML = `
            <span style="font-size:0.9rem; font-weight:500; color:var(--color-primary, #915a28); margin-right:5px;">${user.name}님</span>
            <a href="order-history.html">주문조회</a>
            <a href="#" onclick="logoutUser(event)">로그아웃</a>
            <a href="cart.html" id="cart-nav">장바구니 (0)</a>
        `;
    } else {
        utilityDiv.innerHTML = `
            <a href="login.html">로그인</a>
            <a href="order-history.html">주문조회</a>
            <a href="cart.html" id="cart-nav">장바구니 (0)</a>
        `;
    }
    updateCartCount();
}

function logoutUser(e) {
    if(e) e.preventDefault();
    localStorage.removeItem('yw_jwt_token');
    localStorage.removeItem('yw_user');
    alert('로그아웃되었습니다.');
    window.location.href = 'index.html';
}

document.addEventListener('DOMContentLoaded', () => {
    updateHeaderAuthUI();
});

// Login Modal Handlers
function openLoginModal(e) {
    if(e) e.preventDefault();
    window.location.href = 'login.html';
}
