// 영월고향방앗간 공통 스크립트 (페이지 트랜지션, 장바구니 & JWT 로그인 상태 관리)

function triggerCartBadgePulse() {
    const badge = document.querySelector('.cart-badge');
    if (!badge) return;
    badge.classList.remove('badge-pulse');
    void badge.offsetWidth; // Reflow 유도로 애니메이션 리트리거
    badge.classList.add('badge-pulse');
}

function updateCartCount(shouldPulse = false) {
    const cart = JSON.parse(localStorage.getItem('yw_cart')) || [];
    let totalCount = 0;
    cart.forEach(item => {
        totalCount += item.quantity;
    });
    
    const cartNavs = document.querySelectorAll('a[href*="cart"], #cart-nav');
    cartNavs.forEach(nav => {
        if(nav.innerText.includes('장바구니') || nav.id === 'cart-nav') {
            if (totalCount > 0) {
                nav.innerHTML = `장바구니 <span class="cart-badge">${totalCount}</span>`;
            } else {
                nav.innerHTML = `장바구니 (0)`;
            }
        }
    });

    if (shouldPulse) {
        triggerCartBadgePulse();
    }
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
    updateCartCount(true);
    
    if (redirect) {
        if (confirm('장바구니에 상품이 담겼습니다. 장바구니로 이동하시겠습니까?')) {
            window.location.href = '/cart';
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
            <a href="/order-history">주문조회</a>
            <a href="#" onclick="logoutUser(event)">로그아웃</a>
            <a href="/cart" id="cart-nav">장바구니 (0)</a>
        `;
    } else {
        utilityDiv.innerHTML = `
            <a href="/login">로그인</a>
            <a href="/order-history">주문조회</a>
            <a href="/cart" id="cart-nav">장바구니 (0)</a>
        `;
    }
    updateCartCount();
}

function logoutUser(e) {
    if(e) e.preventDefault();
    localStorage.removeItem('yw_jwt_token');
    localStorage.removeItem('yw_user');
    alert('로그아웃되었습니다.');
    window.location.href = '/';
}

// 페이지 전환(Smooth Page Transition) 시스템
function initPageTransitions() {
    document.body.classList.add('page-loaded');

    document.addEventListener('click', (e) => {
        const anchor = e.target.closest('a');
        if (!anchor) return;
        const href = anchor.getAttribute('href');
        
        // 외부 링크, 앵커, JS 스크립트 실행 링크 등은 제외
        if (!href || href.startsWith('#') || href.startsWith('javascript:') || anchor.target === '_blank' || anchor.hasAttribute('onclick')) {
            return;
        }
        
        // 동일 도메인 내 내부 페이지 이동 시 페이드아웃 후 전환
        if (href.startsWith('/') || href.startsWith(window.location.origin)) {
            e.preventDefault();
            document.body.classList.remove('page-loaded');
            setTimeout(() => {
                window.location.href = href;
            }, 200);
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    updateHeaderAuthUI();
    initPageTransitions();
});

// 브라우저 뒤로가기/앞으로가기 BFCache 호환성 처리
window.addEventListener('pageshow', (e) => {
    document.body.classList.add('page-loaded');
});

// Login Modal Handlers
function openLoginModal(e) {
    if(e) e.preventDefault();
    window.location.href = '/login';
}
