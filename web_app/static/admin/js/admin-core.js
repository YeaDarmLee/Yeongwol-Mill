function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

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
    let container = document.getElementById('admin-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'admin-toast-container';
        container.style.cssText = `
            position: fixed;
            top: 24px;
            right: 24px;
            z-index: 999999;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
        `;
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.style.cssText = `
        pointer-events: auto;
        min-width: 280px;
        max-width: 420px;
        background: #ffffff;
        color: #2c1d11;
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
        display: flex;
        align-items: center;
        gap: 12px;
        font-family: 'Noto Sans KR', sans-serif;
        font-size: 0.9rem;
        font-weight: 500;
        border-left: 5px solid #8D6E63;
        transform: translateX(120%);
        transition: transform 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.275), opacity 0.3s ease;
        opacity: 0;
    `;

    let iconHtml = '<i class="fa-solid fa-circle-info" style="color:#1565c0; font-size:1.2rem;"></i>';
    if (type === 'warning') {
        toast.style.borderLeftColor = '#f57c00';
        iconHtml = '<i class="fa-solid fa-triangle-exclamation" style="color:#f57c00; font-size:1.2rem;"></i>';
    } else if (type === 'error') {
        toast.style.borderLeftColor = '#d32f2f';
        iconHtml = '<i class="fa-solid fa-circle-xmark" style="color:#d32f2f; font-size:1.2rem;"></i>';
    } else if (type === 'success') {
        toast.style.borderLeftColor = '#2e7d32';
        iconHtml = '<i class="fa-solid fa-circle-check" style="color:#2e7d32; font-size:1.2rem;"></i>';
    }

    toast.innerHTML = `
        <div>${iconHtml}</div>
        <div style="flex:1; line-height:1.4;">${message}</div>
        <button type="button" style="background:none; border:none; color:#999; font-size:1.1rem; cursor:pointer; padding:0 4px;" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.style.transform = 'translateX(0)';
        toast.style.opacity = '1';
    });

    setTimeout(() => {
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 400);
    }, 3500);
}

// 2. 커스텀 Confirm 다이얼로그 모달 (Promise 기반)
function customConfirm(message, title = '확인 요청') {
    return new Promise((resolve) => {
        const existingModal = document.getElementById('admin-custom-confirm-modal');
        if (existingModal) existingModal.remove();

        const backdrop = document.createElement('div');
        backdrop.id = 'admin-custom-confirm-modal';
        backdrop.style.cssText = `
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: rgba(0, 0, 0, 0.45);
            backdrop-filter: blur(4px);
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s ease;
        `;

        const card = document.createElement('div');
        card.style.cssText = `
            background: #ffffff;
            border-radius: 12px;
            width: 90%;
            max-width: 420px;
            padding: 24px 20px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
            transform: scale(0.92);
            transition: transform 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            font-family: 'Noto Sans KR', sans-serif;
        `;

        card.innerHTML = `
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:14px;">
                <div style="width:40px; height:40px; border-radius:50%; background:#fff3e0; display:flex; align-items:center; justify-content:center; color:#e65100; font-size:1.3rem; flex-shrink:0;">
                    <i class="fa-solid fa-circle-question"></i>
                </div>
                <div style="font-size:1.05rem; font-weight:700; color:#2c3e50;">${title}</div>
            </div>
            <div style="font-size:0.93rem; color:#4a5568; line-height:1.5; margin-bottom:24px; white-space:pre-wrap;">${message}</div>
            <div style="display:flex; justify-content:flex-end; gap:10px;">
                <button id="confirm-btn-cancel" style="padding:8px 18px; border-radius:6px; border:1px solid #cbd5e0; background:#f7fafc; color:#4a5568; font-weight:600; font-size:0.88rem; cursor:pointer;">취소</button>
                <button id="confirm-btn-ok" style="padding:8px 20px; border-radius:6px; border:none; background:#2b6cb0; color:#ffffff; font-weight:600; font-size:0.88rem; cursor:pointer; box-shadow:0 2px 6px rgba(43,108,176,0.3);">확인</button>
            </div>
        `;

        backdrop.appendChild(card);
        document.body.appendChild(backdrop);

        requestAnimationFrame(() => {
            backdrop.style.opacity = '1';
            card.style.transform = 'scale(1)';
        });

        const closeConfirm = (result) => {
            backdrop.style.opacity = '0';
            card.style.transform = 'scale(0.92)';
            setTimeout(() => {
                backdrop.remove();
                resolve(result);
            }, 180);
        };

        backdrop.querySelector('#confirm-btn-ok').onclick = () => closeConfirm(true);
        backdrop.querySelector('#confirm-btn-cancel').onclick = () => closeConfirm(false);
        backdrop.onclick = (e) => { if (e.target === backdrop) closeConfirm(false); };
    });
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

    // 페이지별 데이터 로드 (0ms instant skeleton clear)
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
            renderTableSkeleton('orders-tbody', 10, 5);
            loadOrders();
        }
    }
    else if (actualPage === 'products' && typeof loadProducts === 'function') {
        renderTableSkeleton('products-tbody', 6, 5);
        loadProducts();
    }
    else if (actualPage === 'customers' && typeof loadCustomers === 'function') {
        renderTableSkeleton('customers-tbody', 8, 5);
        loadCustomers();
    }
    else if (actualPage === 'audit' && typeof loadAuditLogs === 'function') {
        renderTableSkeleton('audit-tbody', 9, 5);
        loadAuditLogs();
    }
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
        let resp = await fetch(cacheBustUrl);
        if (!resp.ok && url.startsWith('/static/admin/')) {
            const altUrl = url.replace('/static/admin/', '/admin/');
            resp = await fetch(`${altUrl}?t=${Date.now()}`);
        }
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
    const loginHtml = await fetchPartial('/admin/components/login.html');
    if (loginHtml) {
        const loginContainer = document.getElementById('login-container');
        if (loginContainer) loginContainer.innerHTML = loginHtml;
    }

    const sidebarHtml = await fetchPartial('/admin/components/sidebar.html');
    if (sidebarHtml) {
        const sidebarContainer = document.getElementById('sidebar-container');
        if (sidebarContainer) sidebarContainer.innerHTML = sidebarHtml;
        initSidebarAccordions();
    }

    // 2. 페이지 뷰 모듈 (대시보드, 주문, 상품, 회원, 감사로그)
    const pages = ['dashboard', 'orders', 'products', 'customers', 'audit'];
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
        const pageHtmls = await Promise.all(pages.map(p => fetchPartial(`/admin/pages/${p}.html`)));
        pageHtmls.forEach(html => {
            if (html) mainContent.insertAdjacentHTML('beforeend', html);
        });
    }

    // 3. 팝업 모달 모듈 (주문상세, 환불확인, 회원수정, 상품수정, 상품생성)
    const modals = ['order-detail', 'refund-confirm', 'customer-edit', 'product-edit', 'product-create'];
    const modalContainer = document.getElementById('modal-container');
    if (modalContainer) {
        const modalHtmls = await Promise.all(modals.map(m => fetchPartial(`/admin/components/modals/${m}.html`)));
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

// 브라우저 기본 alert 시스템 오버라이딩 (커스텀 alert 자동 전환)
window.alert = function (message) {
    if (typeof customAlert === 'function') {
        customAlert(message, 'info');
    }
};

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

/**
 * 리스트 테이블 스켈레톤(Skeleton UI) 로딩 플레이스홀더 렌더러
 * @param {string} tbodyId 
 * @param {number} colsCount 
 * @param {number} rowsCount 
 */
function renderTableSkeleton(tbodyId, colsCount = 6, rowsCount = 5) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.classList.remove('fade-in-table');
    let rowsHtml = '';
    for (let r = 0; r < rowsCount; r++) {
        let colsHtml = '';
        for (let c = 0; c < colsCount; c++) {
            const randomWidth = Math.floor(Math.random() * 35) + 55;
            colsHtml += `<td style="padding:0.9rem 0.8rem;"><div class="skeleton-bar" style="width:${randomWidth}%;"></div></td>`;
        }
        rowsHtml += `<tr>${colsHtml}</tr>`;
    }
    tbody.innerHTML = rowsHtml;
}

