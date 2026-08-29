/* customers.js: 회원 목록, 서버사이드 검색/필터/페이지네이션, 회원 정보 수정 모듈 */

let allCustomersData = [];
let customersCurrentPage = 1;
const CUSTOMERS_PAGE_LIMIT = 10;

async function loadCustomers(page = null) {
    if (page !== null) customersCurrentPage = page;
    renderTableSkeleton('customers-tbody', 8, 5);

    try {
        const params = new URLSearchParams();
        params.set('page', customersCurrentPage);
        params.set('limit', CUSTOMERS_PAGE_LIMIT);

        const keyword = document.getElementById('customer-search-input')?.value.trim() || '';
        const status = document.getElementById('customer-status-filter')?.value || '';

        if (keyword) params.set('keyword', keyword);
        if (status) params.set('status', status);

        const resp = await fetch(`/api/admin/customers?${params.toString()}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();
        allCustomersData = data.customers || [];
        renderCustomerTable(data.customers);
        renderPaginationBar('customers-pagination', data.pagination, 'customersGoPage');

    } catch (err) { console.error('회원 데이터 로드 예외:', err); }
}

function customersGoPage(page) {
    customersCurrentPage = page;
    loadCustomers(page);
}

function filterCustomerList() {
    customersCurrentPage = 1;
    loadCustomers();
}

function resetCustomerFilters() {
    const kw = document.getElementById('customer-search-input');
    const st = document.getElementById('customer-status-filter');
    if (kw) kw.value = '';
    if (st) st.value = '';
    customersCurrentPage = 1;
    loadCustomers();
}

function renderCustomerTable(customers) {
    const tbody = document.getElementById('customers-tbody');
    if (!tbody) return;

    if (!customers || customers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#777; padding:1.5rem;">검색 조건에 일치하는 회원이 없습니다.</td></tr>`;
        return;
    }

    tbody.innerHTML = customers.map(c => `
        <tr>
            <td>${c.id}</td>
            <td><strong>${c.name === '(이름 없음)' ? '<span style="color:#aaa;">미입력</span>' : (c.name || '-')}</strong></td>
            <td>${c.email || '-'}</td>
            <td>${c.phone || '-'}</td>
            <td><span class="status-badge ${c.status === 'SUSPENDED' ? 'status-CANCELLED' : 'status-PREPARING'}">${c.status === 'SUSPENDED' ? '계정정지' : '정상'}</span></td>
            <td>${c.marketing_sms_agreed != null ? (c.marketing_sms_agreed ? '동의' : '미동의') : '-'} / ${c.marketing_email_agreed != null ? (c.marketing_email_agreed ? '동의' : '미동의') : '-'}</td>
            <td style="font-size:0.8rem; color:#777;">${c.created_at || '-'}</td>
            <td>
                <button class="btn-action" style="padding:2px 8px; font-size:0.75rem;" onclick="openEditCustomerModal(${c.id})">수정</button>
                <button class="btn-action" style="padding:2px 8px; font-size:0.75rem; color:${c.status === 'SUSPENDED' ? '#2e7d32' : '#c62828'};" onclick="toggleCustomerStatus(${c.id}, '${c.status === 'SUSPENDED' ? 'ACTIVE' : 'SUSPENDED'}')">
                    ${c.status === 'SUSPENDED' ? '정지 해제' : '계정 정지'}
                </button>
            </td>
        </tr>
    `).join('');
    tbody.classList.add('fade-in-table');
}

async function toggleCustomerStatus(userId, newStatus) {
    const actionText = newStatus === 'SUSPENDED' ? '정지' : '정지 해제';
    const confirmed = await customConfirm(`해당 회원의 계정을 ${actionText} 처리하시겠습니까?`, '회원 상태 변경');
    if (!confirmed) return;
    try {
        const resp = await fetch(`/api/admin/customers/${userId}/status`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        const data = await resp.json();
        if (resp.ok) { customAlert(data.message || `회원 상태가 ${actionText}되었습니다.`, 'success'); loadCustomers(); }
        else customAlert(data.error || '회원 상태 변경 실패', 'error');
    } catch (err) { console.error(err); customAlert('회원 상태 변경 중 오류가 발생했습니다.', 'error'); }
}

function openEditCustomerModal(userId) {
    const u = allCustomersData.find(c => c.id === userId);
    if (!u) return;
    document.getElementById('edit-cust-id').value = u.id;
    document.getElementById('edit-cust-name').value = u.name === '(이름 없음)' ? '' : (u.name || '');
    document.getElementById('edit-cust-email').value = u.email || '';
    document.getElementById('edit-cust-phone').value = u.phone === '-' ? '' : (u.phone || '');
    document.getElementById('edit-cust-status').value = u.status === 'SUSPENDED' ? 'SUSPENDED' : 'ACTIVE';
    document.getElementById('edit-cust-newpass').value = '';
    openModal('editCustomerModal');
}

function generateTempPassword() {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let tempPass = 'yw';
    for (let i = 0; i < 5; i++) tempPass += chars.charAt(Math.floor(Math.random() * chars.length));
    tempPass += '!';
    const passInput = document.getElementById('edit-cust-newpass');
    passInput.value = tempPass;
    passInput.focus();
    customAlert(`임시 비밀번호 [ ${tempPass} ] 생성 완료!\n[수정 사항 저장] 버튼으로 최종 적용하세요.`, 'success');
}

async function submitEditCustomer(btnEl) {
    const userId = document.getElementById('edit-cust-id').value;
    const name = document.getElementById('edit-cust-name').value.trim();
    const email = document.getElementById('edit-cust-email').value.trim();
    const phone = document.getElementById('edit-cust-phone').value.trim();
    const status = document.getElementById('edit-cust-status').value;
    const new_password = document.getElementById('edit-cust-newpass').value.trim();

    if (!email) { customAlert('이메일 주소를 입력해 주세요.', 'error'); return; }

    const originalText = btnEl ? btnEl.innerText : '수정 사항 저장';
    if (btnEl) { btnEl.disabled = true; btnEl.innerText = '저장 중...'; }

    try {
        const resp = await fetch(`/api/admin/customers/${userId}`, {
            method: 'PATCH',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, phone, status, new_password })
        });
        const data = await resp.json();
        if (resp.ok) { closeModal('editCustomerModal'); loadCustomers(); customAlert(data.message || '회원 정보가 성공적으로 변경되었습니다.', 'success'); }
        else customAlert(data.error || '회원 정보 수정 실패', 'error');
    } catch (err) { console.error(err); customAlert('수정 처리 중 오류가 발생했습니다.', 'error'); }
    finally { if (btnEl) { btnEl.disabled = false; btnEl.innerText = originalText; } }
}
