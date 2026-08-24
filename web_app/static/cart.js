// 영월고향방앗간 공통 스크립트 (페이지 트랜지션, 장바구니, 전역 커스텀 Alert & JWT 로그인 상태 관리)

let _globalAlertCallback = null;
let _globalConfirmOnConfirm = null;
let _globalConfirmOnCancel = null;

// 전역 브랜드 커스텀 Alert / Confirm 모달 동적 생성 및 스타일 주입
function ensureGlobalCustomModal() {
    if (document.getElementById('ywGlobalAlertModal')) return;

    // 1. 모달 CSS 스타일 동적 주입
    const styleEl = document.createElement('style');
    styleEl.id = 'ywGlobalModalStyle';
    styleEl.innerHTML = `
        .yw-modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.45);
            backdrop-filter: blur(2px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 9999;
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transition: all 0.22s ease-out;
        }
        .yw-modal-overlay.active {
            opacity: 1;
            visibility: visible;
            pointer-events: auto;
        }
        .yw-alert-card {
            background: #ffffff;
            width: 90%;
            max-width: 400px;
            padding: 2rem 1.6rem 1.6rem;
            border-radius: 14px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.16);
            text-align: center;
            border: 1px solid #eaeaea;
            animation: ywPop 0.22s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        @keyframes ywPop {
            from { opacity: 0; transform: scale(0.88); }
            to { opacity: 1; transform: scale(1); }
        }
        .yw-alert-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: #222222;
            margin: 0 0 0.6rem 0;
        }
        .yw-alert-message {
            font-size: 0.95rem;
            color: #444444;
            margin: 0 0 1.6rem 0;
            line-height: 1.55;
            word-break: keep-all;
            white-space: pre-line;
        }
        .yw-alert-btn-group {
            display: flex;
            gap: 0.6rem;
            justify-content: center;
        }
        .yw-btn-confirm {
            flex: 1;
            height: 44px;
            background: var(--color-primary, #915a28);
            color: #ffffff;
            border: none;
            border-radius: 8px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s ease;
        }
        .yw-btn-confirm:hover {
            background: var(--color-primary-hover, #77491f);
        }
        .yw-btn-cancel {
            flex: 1;
            height: 44px;
            background: #f3f3f3;
            color: #555555;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s ease;
        }
        .yw-btn-cancel:hover {
            background: #e5e5e5;
        }
    `;
    document.head.appendChild(styleEl);

    // 2. 모달 HTML DOM 동적 추가
    const modalHTML = `
        <!-- 전역 커스텀 Alert 모달 -->
        <div id="ywGlobalAlertModal" class="yw-modal-overlay">
            <div class="yw-alert-card">
                <h3 id="ywAlertTitle" class="yw-alert-title">알림</h3>
                <p id="ywAlertMessage" class="yw-alert-message"></p>
                <div class="yw-alert-btn-group">
                    <button type="button" class="yw-btn-confirm" onclick="closeCustomAlert()">확인</button>
                </div>
            </div>
        </div>

        <!-- 전역 커스텀 Confirm 모달 -->
        <div id="ywGlobalConfirmModal" class="yw-modal-overlay">
            <div class="yw-alert-card">
                <h3 id="ywConfirmTitle" class="yw-alert-title">확인</h3>
                <p id="ywConfirmMessage" class="yw-alert-message"></p>
                <div class="yw-alert-btn-group">
                    <button type="button" class="yw-btn-cancel" onclick="closeCustomConfirm(false)">취소</button>
                    <button type="button" class="yw-btn-confirm" onclick="closeCustomConfirm(true)">확인</button>
                </div>
            </div>
        </div>
    `;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = modalHTML;
    document.body.appendChild(wrapper);
}

// 전역 브랜드 커스텀 Alert 함수
function customAlert(message, type = 'success', callback = null) {
    ensureGlobalCustomModal();
    const modal = document.getElementById('ywGlobalAlertModal');
    const titleEl = document.getElementById('ywAlertTitle');
    const msgEl = document.getElementById('ywAlertMessage');

    if (!modal) return;

    msgEl.innerHTML = String(message || '').replace(/\n/g, '<br>');
    _globalAlertCallback = callback;

    if (type === 'error' || String(message).includes('오류') || String(message).includes('실패') || String(message).includes('필수')) {
        titleEl.innerText = '안내';
    } else {
        titleEl.innerText = '알림';
    }

    modal.classList.add('active');
}

function closeCustomAlert() {
    const modal = document.getElementById('ywGlobalAlertModal');
    if (modal) modal.classList.remove('active');
    if (_globalAlertCallback) {
        const cb = _globalAlertCallback;
        _globalAlertCallback = null;
        setTimeout(() => { cb(); }, 150);
    }
}

// 전역 브랜드 커스텀 Confirm 함수
function customConfirm(message, onConfirm = null, onCancel = null) {
    ensureGlobalCustomModal();
    const modal = document.getElementById('ywGlobalConfirmModal');
    const msgEl = document.getElementById('ywConfirmMessage');

    if (!modal) return;

    msgEl.innerHTML = String(message || '').replace(/\n/g, '<br>');
    _globalConfirmOnConfirm = onConfirm;
    _globalConfirmOnCancel = onCancel;

    modal.classList.add('active');
}

function closeCustomConfirm(isConfirmed) {
    const modal = document.getElementById('ywGlobalConfirmModal');
    if (modal) modal.classList.remove('active');
    setTimeout(() => {
        if (isConfirmed && _globalConfirmOnConfirm) {
            _globalConfirmOnConfirm();
        } else if (!isConfirmed && _globalConfirmOnCancel) {
            _globalConfirmOnCancel();
        }
        _globalConfirmOnConfirm = null;
        _globalConfirmOnCancel = null;
    }, 150);
}

// 브라우저 시스템 alert() 및 confirm() 전역 가로채기 (Global Override)
window.alert = function (message) {
    customAlert(message);
};

function triggerCartBadgePulse() {
    const badge = document.querySelector('.cart-badge');
    if (!badge) return;
    
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }
    
    badge.classList.remove('badge-pulse');
    void badge.offsetWidth;
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
        if (nav.innerText.includes('장바구니') || nav.id === 'cart-nav') {
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
        customConfirm('장바구니에 상품이 담겼습니다.\n장바구니로 이동하시겠습니까?', () => {
            window.location.href = '/cart';
        });
    }
}

function updateHeaderAuthUI() {
    const token = localStorage.getItem('yw_jwt_token');
    const user = JSON.parse(localStorage.getItem('yw_user') || 'null');
    
    const utilityDiv = document.querySelector('.utility');
    if (!utilityDiv) return;

    if (token && user) {
        utilityDiv.innerHTML = `
            <a href="/mypage" style="text-decoration:none;"><span class="user-badge" style="cursor:pointer;">${user.name}님</span></a>
            <a href="/order-history" class="header-btn">주문조회</a>
            <a href="/cart" id="cart-nav" class="header-btn">장바구니 (0)</a>
            <a href="#" onclick="logoutUser(event)" class="header-btn btn-logout">로그아웃</a>
        `;
    } else {
        utilityDiv.innerHTML = `
            <a href="/login" class="header-btn">로그인</a>
            <a href="/order-history" class="header-btn">주문조회</a>
            <a href="/cart" id="cart-nav" class="header-btn">장바구니 (0)</a>
        `;
    }
    updateCartCount();
}

function logoutUser(e) {
    if (e) e.preventDefault();
    localStorage.removeItem('yw_jwt_token');
    localStorage.removeItem('yw_user');
    customAlert('로그아웃되었습니다.', 'success', () => {
        window.location.href = '/';
    });
}

// 페이지 전환(Smooth Page Transition) 시스템
function initPageTransitions() {
    document.body.classList.remove('page-fade-out');

    document.addEventListener('click', (e) => {
        const anchor = e.target.closest('a');
        if (!anchor) return;
        const href = anchor.getAttribute('href');
        
        if (!href || href.startsWith('#') || href.startsWith('javascript:') || anchor.target === '_blank' || anchor.hasAttribute('onclick')) {
            return;
        }
        
        if (href.startsWith('/') || href.startsWith(window.location.origin)) {
            e.preventDefault();
            document.body.classList.add('page-fade-out');
            setTimeout(() => {
                window.location.href = href;
            }, 180);
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    ensureGlobalCustomModal();
    updateHeaderAuthUI();
    initPageTransitions();
});

// 브라우저 뒤로가기/앞으로가기 BFCache 호환성 처리
window.addEventListener('pageshow', (e) => {
    document.body.classList.remove('page-fade-out');
});

// Login Modal Handlers
function openLoginModal(e) {
    if (e) e.preventDefault();
    window.location.href = '/login';
}
