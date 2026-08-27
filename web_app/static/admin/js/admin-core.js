function initSidebarAccordions() {
    document.querySelectorAll('.menu-group-header').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const group = btn.dataset.group;
            const submenu = document.getElementById(`submenu-${group}`);
            const isExpanded = btn.getAttribute('aria-expanded') === 'true';
            
            btn.setAttribute('aria-expanded', !isExpanded);
            if (submenu) {
                if (isExpanded) {
                    submenu.classList.add('collapsed');
                } else {
                    submenu.classList.remove('collapsed');
                }
            }
        });
    });
}
let dashboardPollInterval = null;

function customAlert(message, type = 'info') {
    alert(`[${type.toUpperCase()}] ${message}`);
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('active');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('active');
}

function getOrderStatusKo(status) {
    const map = {
        'PENDING': '주문 대기',
        'CONFIRMED': '주문 확정',
        'PREPARING': '상품 준비중',
        'READY_TO_SHIP': '배송 준비중',
        'SHIPPING': '배송 중',
        'DELIVERED': '배송 완료',
        'CANCELLED': '주문 취소'
    };
    return map[status] || status;
}

function getPaymentStatusKo(status) {
    const map = {
        'PENDING': '결제 대기',
        'PAID': '결제 완료',
        'PARTIALLY_REFUNDED': '부분 환불',
        'REFUNDED': '전액 환불',
        'FAILED': '결제 실패'
    };
    return map[status] || status;
}

function getRefundStatusKo(status) {
    const map = {
        'PENDING': '접수 대기',
        'PROCESSING': '처리 중',
        'COMPLETED': '환불 완료',
        'RECONCILING': '상태 대조중',
        'REJECTED': '거절됨'
    };
    return map[status] || status;
}

let currentActivePage = '';

function navigatePage(pageName, updateHash = true) {
    const targetHash = `#${pageName}`;

    if (updateHash && window.location.hash !== targetHash) {
        window.location.hash = pageName;
        return;
    }

    if (dashboardPollInterval) {
        clearInterval(dashboardPollInterval);
        dashboardPollInterval = null;
    }

    document.querySelectorAll('.page-view').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.sidebar-menu li').forEach(el => el.classList.remove('active'));

    // orders/subtab 및 cs/subtab 파싱
    let actualPage = pageName;
    let subTab = null;
    if (pageName.startsWith('orders/')) {
        actualPage = 'orders';
        subTab = pageName.split('/')[1];
    } else if (pageName.startsWith('cs/')) {
        actualPage = 'cs';
        subTab = pageName.split('/')[1];
    }

    // 유효한 파서 매핑
    const validOrderSubtabs = ['all', 'pending', 'confirmed', 'preparing', 'ready_to_ship', 'shipping', 'delivered'];
    const validCsSubtabs = ['cancel', 'exchange', 'return', 'refund'];

    if (actualPage === 'orders' && subTab && !validOrderSubtabs.includes(subTab)) {
        window.location.hash = '#orders/all';
        return;
    }
    if (actualPage === 'cs' && subTab && !validCsSubtabs.includes(subTab)) {
        window.location.hash = '#cs/cancel';
        return;
    }

    // 메인 View Target (orders와 cs 모두 view-orders 공유)
    const targetViewId = (actualPage === 'orders' || actualPage === 'cs') ? 'view-orders' : `view-${actualPage}`;
    const targetView = document.getElementById(targetViewId);

    if (targetView) {
        targetView.classList.remove('active');
        void targetView.offsetWidth; // trigger reflow for smooth animation
        targetView.classList.add('active');
    }

    // Active 메뉴 및 아코디언 Auto Expand
    let targetMenuId = `menu-${actualPage}`;
    if (subTab) {
        targetMenuId = `menu-${actualPage}-${subTab}`;
    }
    const targetMenu = document.getElementById(targetMenuId);
    if (targetMenu) targetMenu.classList.add('active');

    if (actualPage === 'orders') {
        const groupBtn = document.querySelector('.menu-group-header[data-group="fulfillment"]');
        const submenu = document.getElementById('submenu-fulfillment');
        if (groupBtn) groupBtn.setAttribute('aria-expanded', 'true');
        if (submenu) submenu.classList.remove('collapsed');
    } else if (actualPage === 'cs') {
        const groupBtn = document.querySelector('.menu-group-header[data-group="cs"]');
        const submenu = document.getElementById('submenu-cs');
        if (groupBtn) groupBtn.setAttribute('aria-expanded', 'true');
        if (submenu) submenu.classList.remove('collapsed');
    }

    currentActivePage = actualPage;

    // 페이지별 데이터 로드
    if (actualPage === 'dashboard') {
        if (typeof loadDashboardMetrics === 'function') loadDashboardMetrics();
        dashboardPollInterval = setInterval(() => {
            if (typeof loadDashboardMetrics === 'function') loadDashboardMetrics(true);
        }, 300000);
    }
    else if (actualPage === 'orders' || actualPage === 'cs') {
        const pageKey = (actualPage === 'cs') ? `cs_${subTab}` : (subTab || 'all');
        if (typeof switchOperationsPage === 'function') {
            switchOperationsPage(pageKey);
        } else if (typeof switchOrderSubTab === 'function') {
            switchOrderSubTab(pageKey);
        } else if (typeof loadOrders === 'function') {
            loadOrders();
        }
    }
    else if (actualPage === 'products' && typeof loadProducts === 'function') loadProducts();
    else if (actualPage === 'customers' && typeof loadCustomers === 'function') loadCustomers();
    else if (actualPage === 'audit' && typeof loadAuditLogs === 'function') loadAuditLogs();
}

function handleHashRouting() {
    let rawHash = window.location.hash.replace('#', '') || 'dashboard';

    // Canonical Fallback
    if (rawHash === 'orders') {
        window.location.hash = '#orders/all';
        return;
    }
    if (rawHash === 'cs') {
        window.location.hash = '#cs/cancel';
        return;
    }

    navigatePage(rawHash, false);
}

// 비동기 HTML 컴포넌트 및 페이지 모듈 로더
async function fetchPartial(url) {
    try {
        const cacheBustUrl = `${url}?t=${Date.now()}`;
        const resp = await fetch(cacheBustUrl);
        if (resp.ok) {
            return await resp.text();
        }
    } catch (e) {
        console.error(`Error loading partial ${url}:`, e);
    }
    return null;
}

async function loadAdminPartials() {
    // 1. 공통 컴포넌트 (로그인 폼, 사이드바)
    const loginHtml = await fetchPartial('/static/admin/components/login.html');
    if (loginHtml) {
        const loginContainer = document.getElementById('login-container');
        if (loginContainer) loginContainer.innerHTML = loginHtml;
    }

    const sidebarHtml = await fetchPartial('/static/admin/components/sidebar.html');
    if (sidebarHtml) {
        const sidebarContainer = document.getElementById('sidebar-container');
        if (sidebarContainer) sidebarContainer.innerHTML = sidebarHtml;
        initSidebarAccordions();
    }

    // 2. 페이지 뷰 모듈 (대시보드, 주문, 상품, 회원, 감사로그)
    const pages = ['dashboard', 'orders', 'products', 'customers', 'audit'];
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
        const pageHtmls = await Promise.all(pages.map(p => fetchPartial(`/static/admin/pages/${p}.html`)));
        pageHtmls.forEach(html => {
            if (html) mainContent.insertAdjacentHTML('beforeend', html);
        });
    }

    // 3. 팝업 모달 모듈 (주문상세, 환불확인, 회원수정, 상품수정, 상품생성)
    const modals = ['order-detail', 'refund-confirm', 'customer-edit', 'product-edit', 'product-create'];
    const modalContainer = document.getElementById('modal-container');
    if (modalContainer) {
        const modalHtmls = await Promise.all(modals.map(m => fetchPartial(`/static/admin/components/modals/${m}.html`)));
        modalHtmls.forEach(html => {
            if (html) modalContainer.insertAdjacentHTML('beforeend', html);
        });
    }
}

function showLoginForm() {
    const loginContainer = document.getElementById('login-container');
    if (loginContainer) loginContainer.style.display = 'flex';
    const loginSec = document.getElementById('login-section');
    if (loginSec) loginSec.style.display = 'block';
    const adminApp = document.getElementById('admin-app');
    if (adminApp) adminApp.style.display = 'none';
}

function showDashboard() {
    const loginContainer = document.getElementById('login-container');
    if (loginContainer) loginContainer.style.display = 'none';
    const loginSec = document.getElementById('login-section');
    if (loginSec) loginSec.style.display = 'none';
    const adminApp = document.getElementById('admin-app');
    if (adminApp) adminApp.style.display = 'flex';

    const adminUser = JSON.parse(localStorage.getItem('yw_admin_user') || '{}');
    const userDisplay = document.getElementById('admin-user-display');
    if (userDisplay) {
        userDisplay.innerText = `${adminUser.name || '관리자'} (${adminUser.role || 'ADMIN'})`;
    }
}

async function handleAdminLogin(e) {
    e.preventDefault();
    const email = document.getElementById('admin-email').value.trim();
    const password = document.getElementById('admin-password').value.trim();

    try {
        const resp = await fetch('/api/admin/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await resp.json();
        if (resp.ok) {
            adminToken = data.token;
            localStorage.setItem('yw_admin_token', data.token);
            localStorage.setItem('yw_admin_user', JSON.stringify(data.admin));
            showDashboard();
            handleHashRouting();
        } else {
            customAlert(data.error || '로그인 실패', 'error');
        }
    } catch (err) {
        console.error(err);
        customAlert('로그인 중 오류가 발생했습니다.', 'error');
    }
}

function logoutAdmin() {
    if (dashboardPollInterval) {
        clearInterval(dashboardPollInterval);
        dashboardPollInterval = null;
    }
    localStorage.removeItem('yw_admin_token');
    localStorage.removeItem('yw_admin_user');
    adminToken = '';
    showLoginForm();
}

// 이벤트 및 세션 초기화
document.addEventListener('DOMContentLoaded', async () => {
    adminToken = localStorage.getItem('yw_admin_token') || '';

    // 토큰이 존재하면 partials 로딩 전에 즉시 대시보드 구조를 먼저 활성화하여 로그인 화면 튕김 방지
    if (adminToken) {
        showDashboard();
    } else {
        showLoginForm();
    }

    await loadAdminPartials();
    window.addEventListener('hashchange', () => handleHashRouting());

    if (adminToken) {
        showDashboard();
        handleHashRouting();
    } else {
        showLoginForm();
    }
});

/**
 * 범용 페이지네이션 바 렌더링 유틸
 * @param {string} containerId  - 삽입할 container element ID
 * @param {object} pagination   - { page, total_pages, total_count }
 * @param {string} onPageClick  - 클릭 시 호출할 JS 함수명 (문자열, 인자로 page 번호 전달)
 */
function renderPaginationBar(containerId, pagination, onPageClick) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!pagination || pagination.total_pages <= 1) {
        container.innerHTML = (pagination && pagination.total_count > 0)
            ? `<div style="font-size:0.82rem; color:#666; margin-top:0.6rem;">전체 <strong>${pagination.total_count}</strong>건</div>`
            : '';
        return;
    }

    const { page, total_pages, total_count } = pagination;

    let btns = '';
    btns += `<button class="btn-action" style="padding:3px 8px;" ${page <= 1 ? 'disabled' : ''} onclick="${onPageClick}(1)">&laquo;</button>`;
    btns += `<button class="btn-action" style="padding:3px 8px;" ${page <= 1 ? 'disabled' : ''} onclick="${onPageClick}(${page - 1})">&lsaquo;</button>`;

    let startP = Math.max(1, page - 2);
    let endP = Math.min(total_pages, startP + 4);
    if (endP - startP < 4) startP = Math.max(1, endP - 4);

    for (let i = startP; i <= endP; i++) {
        const active = i === page
            ? 'background:var(--admin-primary,#8D6E63);color:#fff;font-weight:700;'
            : 'background:#fff;color:#333;';
        btns += `<button class="btn-action" style="padding:3px 9px;${active}" onclick="${onPageClick}(${i})">${i}</button>`;
    }

    btns += `<button class="btn-action" style="padding:3px 8px;" ${page >= total_pages ? 'disabled' : ''} onclick="${onPageClick}(${page + 1})">&rsaquo;</button>`;
    btns += `<button class="btn-action" style="padding:3px 8px;" ${page >= total_pages ? 'disabled' : ''} onclick="${onPageClick}(${total_pages})">&raquo;</button>`;

    container.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.8rem;padding-top:0.6rem;border-top:1px dashed #e0e0e0;">
            <span style="font-size:0.82rem;color:#666;">전체 <strong>${total_count}</strong>건 &middot; ${page} / ${total_pages} 페이지</span>
            <div style="display:flex;gap:3px;">${btns}</div>
        </div>
    `;
}

