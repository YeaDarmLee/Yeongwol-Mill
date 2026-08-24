/* admin-core.js: 관리자 공통 인증, 탭 네비게이션, 모달 및 알림 유틸 */

let adminToken = localStorage.getItem('yw_admin_token') || '';
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

    // updateHash가 true이고 현재 해시와 다를 경우 해시 변경
    // 해시 변경 시 hashchange 이벤트 핸들러가 handleHashRouting()을 통해 1번만 안전하게 호출함
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

    const targetView = document.getElementById(`view-${pageName}`);
    const targetMenu = document.getElementById(`menu-${pageName}`);

    if (targetView) {
        targetView.classList.remove('active');
        void targetView.offsetWidth; // trigger reflow for smooth animation
        targetView.classList.add('active');
    }
    if (targetMenu) targetMenu.classList.add('active');

    currentActivePage = pageName;

    // 페이지별 데이터 로드
    if (pageName === 'dashboard') {
        if (typeof loadDashboardMetrics === 'function') loadDashboardMetrics();
        dashboardPollInterval = setInterval(() => {
            if (typeof loadDashboardMetrics === 'function') loadDashboardMetrics(true);
        }, 300000);
    }
    else if (pageName === 'orders' && typeof loadOrders === 'function') loadOrders();
    else if (pageName === 'products' && typeof loadProducts === 'function') loadProducts();
    else if (pageName === 'customers' && typeof loadCustomers === 'function') loadCustomers();
    else if (pageName === 'audit' && typeof loadAuditLogs === 'function') loadAuditLogs();
}

function handleHashRouting() {
    const hash = window.location.hash.replace('#', '') || 'dashboard';
    navigatePage(hash, false);
}

function showLoginForm() {
    document.getElementById('login-section').style.display = 'block';
    document.getElementById('admin-app').style.display = 'none';
}

function showDashboard() {
    document.getElementById('login-section').style.display = 'none';
    document.getElementById('admin-app').style.display = 'flex';

    const adminUser = JSON.parse(localStorage.getItem('yw_admin_user') || '{}');
    document.getElementById('admin-user-display').innerText = `${adminUser.name || '관리자'} (${adminUser.role || 'ADMIN'})`;
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
document.addEventListener('DOMContentLoaded', () => {
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

