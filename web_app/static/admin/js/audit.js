/* audit.js: 관리자 작업 감사 로그 조회 및 보안 이력 관리 모듈 */

let currentAuditParams = {
    page: 1,
    limit: 15,
    keyword: '',
    action_type: '',
    target_type: ''
};

async function loadAuditLogs(params = {}) {
    currentAuditParams = { ...currentAuditParams, ...params };
    renderTableSkeleton('audit-tbody', 9, 5);
    try {
        const queryStr = new URLSearchParams(
            Object.entries(currentAuditParams).filter(([_, v]) => v !== '' && v !== null && v !== undefined)
        ).toString();

        const resp = await fetch(`/api/admin/audit-logs?${queryStr}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();
        renderAuditTable(data.audit_logs || []);

        if (data.pagination) {
            renderPaginationBar('audit-pagination', data.pagination, (newPage) => {
                changeAuditPage(newPage);
            });
        }
    } catch (err) {
        console.error('감사로그 로드 예외:', err);
    }
}

function renderAuditTable(logs) {
    const tbody = document.getElementById('audit-tbody');
    if (!tbody) return;

    if (!logs || logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:#777; padding:1.5rem;">검색 조건에 일치하는 감사로그가 없습니다.</td></tr>`;
        return;
    }

    tbody.innerHTML = logs.map(a => `
        <tr>
            <td>${a.id}</td>
            <td><strong>${a.admin_email}</strong></td>
            <td><span class="status-badge status-PREPARING">${a.action_type}</span></td>
            <td>${a.target_type || '-'}</td>
            <td>${a.target_id || '-'}</td>
            <td style="max-width:280px; word-break:break-all;">${a.reason || '-'}</td>
            <td><span class="status-badge ${a.result === 'SUCCESS' || a.result === 'COMPLETED' ? 'status-CONFIRMED' : 'status-CANCELLED'}">${a.result}</span></td>
            <td style="font-size:0.8rem; color:#777;">${a.request_ip || '-'}</td>
            <td style="font-size:0.8rem; color:#777;">${a.created_at || '-'}</td>
        </tr>
    `).join('');
    tbody.classList.add('fade-in-table');
}

function filterAuditLogs() {
    const keyword = document.getElementById('audit-keyword-filter').value.trim();
    const action_type = document.getElementById('audit-action-filter').value.trim();
    const target_type = document.getElementById('audit-target-filter').value.trim();

    loadAuditLogs({
        page: 1,
        keyword,
        action_type,
        target_type
    });
}

function resetAuditFilters() {
    document.getElementById('audit-keyword-filter').value = '';
    document.getElementById('audit-action-filter').value = '';
    document.getElementById('audit-target-filter').value = '';

    loadAuditLogs({
        page: 1,
        keyword: '',
        action_type: '',
        target_type: ''
    });
}

function changeAuditPage(page) {
    loadAuditLogs({ page });
}
