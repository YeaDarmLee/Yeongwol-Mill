/* orders.js: Declarative Config 기반 라우트 뷰, Stale Response 방어, 인라인 송장 및 배치 처리 스크립트 */

let currentModalOrderData = null;
let ordersCurrentPage = 1;
const ORDERS_PAGE_LIMIT = 10;
let currentOrderSubTab = 'all';
let selectedOrderIds = new Set();
let currentRequestToken = 0; // Stale Response Race Condition 방어 토큰

// 1. Declarative Config 선언 (주문 워크플로우 & CS 관리)
const ORDER_PAGE_CONFIG = {
    'all': {
        title: '전체 주문 목록',
        description: '영월고향방앗간 전체 주문 내역을 조회하고 상태를 확인합니다.',
        statusFilter: '',
        paymentFilter: '',
        toolbarButtons: ['cancel']
    },
    'pending': {
        title: '1. 신규 주문 관리',
        description: '결제가 완료되어 검수 및 상품 준비(제분/포장)로 전환할 신규 주문입니다.',
        statusFilter: 'PENDING,CONFIRMED',
        paymentFilter: 'PAID,PARTIALLY_REFUNDED',
        toolbarButtons: ['prepare', 'cancel']
    },
    'preparing': {
        title: '상품 준비중 관리',
        description: '상품 포장 및 출고 작업이 진행 중인 주문입니다.',
        statusFilter: 'PREPARING',
        toolbarButtons: ['ready_to_ship', 'cancel']
    },
    'ready_to_ship': {
        title: '배송 준비중 관리 (송장 입력)',
        description: '포장이 완료되어 택배사 인계 및 운송장 번호를 등록하는 단계입니다.',
        statusFilter: 'READY_TO_SHIP',
        toolbarButtons: ['saveTracking', 'ship'],
        inlineTrackingEditable: true
    },
    'shipping': {
        title: '배송중 관리',
        description: '택배사에 인계되어 수령인에게 배송 이동 중인 주문입니다.',
        statusFilter: 'SHIPPING',
        toolbarButtons: ['deliver']
    },
    'delivered': {
        title: '배송 완료 내역',
        description: '수령인에게 최종 전달 완료된 주문 내역입니다.',
        statusFilter: 'DELIVERED',
        toolbarButtons: []
    }
};

const CS_PAGE_CONFIG = {
    'cs_cancel': {
        title: '취소 관리 (CS)',
        description: '고객 또는 관리자에 의해 접수 및 처리된 주문 취소 내역입니다.',
        statusFilter: 'CANCELLED',
        toolbarButtons: ['refresh']
    },
    'cs_exchange': {
        title: '교환 관리 (CS)',
        description: '상품 교환 신청 건의 맞교환 송장 및 재출고 현황을 관리합니다.',
        refundFilter: 'EXCHANGE',
        toolbarButtons: ['refresh']
    },
    'cs_return': {
        title: '반품 관리 (CS)',
        description: '반품 회수 검수 및 상태에 따른 환불 승인 절차를 진행합니다.',
        refundFilter: 'RETURN',
        toolbarButtons: ['refresh']
    },
    'cs_refund': {
        title: '환불 관리 & PG 대조 (CS)',
        description: 'PG 환불 처리 및 PG 미확정(RECONCILE_REQUIRED) 상태를 대조하고 검수합니다.',
        paymentFilter: 'PARTIALLY_REFUNDED',
        toolbarButtons: ['reconcileFilter']
    }
};

// 2. Config 기반 뷰 라우팅 함수 (switchOperationsPage)
async function switchOperationsPage(pageKey) {
    currentOrderSubTab = pageKey;
    selectedOrderIds.clear();
    updateSelectAllCheckboxState();

    const config = ORDER_PAGE_CONFIG[pageKey] || CS_PAGE_CONFIG[pageKey] || ORDER_PAGE_CONFIG['all'];

    // 동적 Page Header 렌더링
    const titleEl = document.getElementById('orders-page-title');
    const descEl = document.getElementById('orders-page-desc');
    if (titleEl) titleEl.innerText = config.title;
    if (descEl) descEl.innerText = config.description;

    // 사이드바 active 매핑
    let targetMenuId = pageKey.startsWith('cs_') ? `menu-cs-${pageKey.replace('cs_', '')}` : `menu-orders-${pageKey}`;
    document.querySelectorAll('.sidebar-menu li').forEach(el => el.classList.remove('active'));
    const menuEl = document.getElementById(targetMenuId);
    if (menuEl) menuEl.classList.add('active');

    // URL 해시 싱크 (orders/subtab, cs/subtab)
    if (pageKey === 'all') {
        window.location.hash = '#orders/all';
    } else if (pageKey.startsWith('cs_')) {
        window.location.hash = `#cs/${pageKey.replace('cs_', '')}`;
    } else {
        window.location.hash = `#orders/${pageKey}`;
    }

    // Badge 및 Toolbar 업데이트
    await loadOrderSubTabCounts();
    renderBatchActionButtons(config.toolbarButtons);

    // 주문 목록 로드
    ordersCurrentPage = 1;
    await loadOrders(config);
}

// 3. Active Queue Badge 조건부 노출 (0건/장애 시 숨김, 1건 이상 노출)
async function loadOrderSubTabCounts() {
    try {
        const resp = await fetch('/api/admin/orders/counts', {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) {
            hideAllBadges();
            return;
        }
        const data = await resp.json();

        // 뱃지 업데이트 (배송완료 생략, 0건 시 display: none)
        ['pending', 'confirmed', 'preparing', 'ready_to_ship', 'shipping',
            'cs_cancel', 'cs_exchange', 'cs_return', 'cs_refund'].forEach(key => {
                const el = document.getElementById(`menu-badge-${key}`);
                if (el) {
                    const count = data[key] || 0;
                    if (count > 0) {
                        el.innerText = count;
                        el.style.display = 'inline-block';
                    } else {
                        el.style.display = 'none';
                    }
                }
            });

        // RECONCILE_REQUIRED 경고 뱃지
        const alertEl = document.getElementById('reconcile-alert-badge');
        const warnEl = document.getElementById('badge-reconcile_warning');
        if (data.reconcile_warning > 0) {
            if (alertEl) alertEl.style.display = 'inline-flex';
            if (warnEl) warnEl.innerText = data.reconcile_warning;
        } else {
            if (alertEl) alertEl.style.display = 'none';
        }
    } catch (err) {
        console.error('Badge API 장애 감지 (경고 숨김 처리):', err);
        hideAllBadges();
    }
}

function hideAllBadges() {
    document.querySelectorAll('.active-queue-badge').forEach(el => el.style.display = 'none');
}

// 4. 동적 Batch Action Buttons 렌더링
function renderBatchActionButtons(toolbarTypes = []) {
    const container = document.getElementById('batch-button-container');
    if (!container) return;

    let buttonsHtml = '';
    toolbarTypes.forEach(type => {
        if (type === 'confirm') {
            buttonsHtml += `<button class="btn-action" style="background:#2e7d32; color:#fff;" onclick="executeBatchCommand('confirm')"><i class="fa-solid fa-check" style="margin-right:4px;"></i> 선택 주문 확인</button>`;
        } else if (type === 'prepare') {
            buttonsHtml += `<button class="btn-action" style="background:#e65100; color:#fff;" onclick="executeBatchCommand('prepare')"><i class="fa-solid fa-box-open" style="margin-right:4px;"></i> 선택 상품 준비중 전환</button>`;
        } else if (type === 'ready_to_ship') {
            buttonsHtml += `<button class="btn-action" style="background:#1565c0; color:#fff;" onclick="executeBatchCommand('ready_to_ship')"><i class="fa-solid fa-tag" style="margin-right:4px;"></i> 선택 배송 준비중 전환</button>`;
        } else if (type === 'saveTracking') {
            buttonsHtml += `<button class="btn-action" style="background:#00796b; color:#fff;" onclick="executeBatchSaveInlineTracking()"><i class="fa-solid fa-floppy-disk" style="margin-right:4px;"></i> 송장 일괄 저장</button>`;
        } else if (type === 'ship') {
            buttonsHtml += `<button class="btn-action" style="background:#2e7d32; color:#fff;" onclick="executeBatchCommand('ship')"><i class="fa-solid fa-truck-fast" style="margin-right:4px;"></i> 선택 배송 시작</button>`;
        } else if (type === 'deliver') {
            buttonsHtml += `<button class="btn-action" style="background:#2e7d32; color:#fff;" onclick="executeBatchCommand('deliver')"><i class="fa-solid fa-house-circle-check" style="margin-right:4px;"></i> 선택 배송 완료 처리</button>`;
        } else if (type === 'cancel') {
            buttonsHtml += `<button class="btn-action" style="background:#c62828; color:#fff;" onclick="executeBatchCommand('cancel')"><i class="fa-solid fa-xmark" style="margin-right:4px;"></i> 선택 주문 취소</button>`;
        } else if (type === 'refresh') {
            buttonsHtml += `<button class="btn-action" style="background:#757575; color:#fff;" onclick="loadOrders()"><i class="fa-solid fa-rotate" style="margin-right:4px;"></i> 내역 새로고침</button>`;
        } else if (type === 'reconcileFilter') {
            buttonsHtml += `<button class="btn-action" style="background:#c62828; color:#fff;" onclick="loadOrders({refund_status:'RECONCILING'})"><i class="fa-solid fa-triangle-exclamation" style="margin-right:4px;"></i> 상태대조중 환불 조회</button>`;
        }
    });

    container.innerHTML = buttonsHtml;
}

// 5. 주문 데이터 로드 & Stale Response Race Condition 방어
async function loadOrders(activeConfig = null, page = null) {
    if (page !== null) ordersCurrentPage = page;
    const requestToken = ++currentRequestToken; // 토큰 증가

    const config = activeConfig || ORDER_PAGE_CONFIG[currentOrderSubTab] || CS_PAGE_CONFIG[currentOrderSubTab] || ORDER_PAGE_CONFIG['all'];

    try {
        const params = new URLSearchParams();
        params.set('page', ordersCurrentPage);
        params.set('limit', ORDERS_PAGE_LIMIT);

        if (config.statusFilter) params.set('order_status', config.statusFilter);
        if (config.paymentFilter) params.set('payment_status', config.paymentFilter);
        if (config.refundFilter) params.set('refund_status', config.refundFilter);

        // 수동 입력 필터 적용
        const kw = document.getElementById('order-keyword-filter')?.value || '';
        if (kw) params.set('keyword', kw);

        const resp = await fetch(`/api/admin/orders?${params.toString()}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();

        // Stale Response 검증: 요청 도중 메뉴가 새로 클릭되었으면 이전 늦은 응답 무시!
        if (requestToken !== currentRequestToken) {
            console.log(`Stale API Response ignored (token: ${requestToken}, current: ${currentRequestToken})`);
            return;
        }

        const tbody = document.getElementById('orders-tbody');
        const countBadge = document.getElementById('orders-page-count-badge');
        if (countBadge) countBadge.innerText = `${(data.pagination?.total_count || 0).toLocaleString()}건`;

        if (!tbody) return;

        if (!data.orders || data.orders.length === 0) {
            tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:#777; padding:2rem;">해당 조건에 맞는 주문 내역이 없습니다.</td></tr>`;
        } else {
            const isReadyToShipView = (config.inlineTrackingEditable === true);
            tbody.innerHTML = data.orders.map(ord => {
                const isChecked = selectedOrderIds.has(ord.id);
                let trackingTdHtml = '';

                if (isReadyToShipView) {
                    trackingTdHtml = `
                        <div style="display:flex; gap:4px; align-items:center;">
                            <select class="inline-courier-select form-control" data-order-id="${ord.id}" style="padding:2px 4px; font-size:0.8rem; width:95px;">
                                ${['CJ대한통운', '우체국택배', '한진택배', '롯데택배', '로젠택배'].map(c =>
                        `<option value="${c}" ${ord.courier_name === c ? 'selected' : ''}>${c}</option>`
                    ).join('')}
                            </select>
                            <input type="text" class="inline-tracking-input form-control" data-order-id="${ord.id}" value="${ord.tracking_number || ''}" placeholder="송장번호 입력" style="padding:2px 6px; font-size:0.8rem; width:130px;">
                        </div>
                    `;
                } else {
                    trackingTdHtml = ord.tracking_number
                        ? `<span style="font-size:0.78rem; color:#2e7d32; font-weight:600;">${ord.courier_name || ''} ${ord.tracking_number}</span>`
                        : `<span style="font-size:0.78rem; color:#d32f2f; font-weight:600;">미등록</span>`;
                }

                return `
                    <tr style="${ord.fulfillment_hold ? 'background:#fff8e1;' : ''}">
                        <td style="text-align:center;">
                            <input type="checkbox" class="order-select-chk" data-order-id="${ord.id}" ${isChecked ? 'checked' : ''} onchange="onOrderSelectChange(${ord.id}, this.checked)">
                        </td>
                        <td>${ord.id}</td>
                        <td>
                            <strong>${ord.order_number}</strong>
                            ${ord.fulfillment_hold ? `<div style="font-size:0.7rem; color:#e65100; font-weight:bold;">⚠ 보류: ${ord.fulfillment_hold_reason || 'CS/대조중'}</div>` : ''}
                        </td>
                        <td>${ord.recipient_name || ord.guest_name || '구매자'}</td>
                        <td>${ord.recipient_phone || '-'}</td>
                        <td><strong>${(ord.total_amount || 0).toLocaleString()}원</strong></td>
                        <td><span class="status-badge status-${ord.order_status}">${getOrderStatusKo(ord.order_status)}</span></td>
                        <td><span class="status-badge status-${ord.payment_status}">${getPaymentStatusKo(ord.payment_status)}</span></td>
                        <td>${trackingTdHtml}</td>
                        <td>
                            <button class="btn-action" style="padding:3px 8px; font-size:0.78rem;" onclick="openOrderDetail(${ord.id})">상세 관리</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        renderPaginationBar('orders-pagination', data.pagination, 'ordersGoPage');
    } catch (err) {
        console.error('주문 목록 로드 실패:', err);
    }
}

// 6. 체크박스 선택 제어
function onOrderSelectChange(orderId, isChecked) {
    if (isChecked) selectedOrderIds.add(orderId);
    else selectedOrderIds.delete(orderId);
    updateSelectAllCheckboxState();
}

function toggleSelectAllOrders(isChecked) {
    document.querySelectorAll('.order-select-chk').forEach(chk => {
        chk.checked = isChecked;
        const oid = parseInt(chk.dataset.orderId);
        if (isChecked) selectedOrderIds.add(oid);
        else selectedOrderIds.delete(oid);
    });
    updateSelectAllCheckboxState();
}

function updateSelectAllCheckboxState() {
    const countEl = document.getElementById('selected-orders-count');
    if (countEl) countEl.innerText = selectedOrderIds.size;
}

// 7. 일괄 Command 실행 및 토스트 처리
async function executeBatchCommand(commandType) {
    if (selectedOrderIds.size === 0) {
        customAlert('선택된 주문이 없습니다. 목록에서 체크박스를 선택해 주세요.', 'error');
        return;
    }

    const orderIds = Array.from(selectedOrderIds);
    let endpoint = '';
    let confirmMsg = '';

    switch (commandType) {
        case 'confirm':
            endpoint = '/api/admin/orders/confirm';
            confirmMsg = `선택한 ${orderIds.length}건의 주문을 [주문 확인] 상태로 변경하시겠습니까?`;
            break;
        case 'prepare':
            endpoint = '/api/admin/orders/prepare';
            confirmMsg = `선택한 ${orderIds.length}건의 주문을 [상품 준비중] 상태로 변경하시겠습니까?`;
            break;
        case 'ready_to_ship':
            endpoint = '/api/admin/orders/ready-to-ship';
            confirmMsg = `선택한 ${orderIds.length}건의 주문을 [배송 준비중] 상태로 전환하시겠습니까?`;
            break;
        case 'ship':
            endpoint = '/api/admin/orders/ship';
            confirmMsg = `선택한 ${orderIds.length}건의 주문의 배송을 시작하시겠습니까? (송장 필수)`;
            break;
        case 'deliver':
            endpoint = '/api/admin/orders/deliver';
            confirmMsg = `선택한 ${orderIds.length}건의 주문을 [배송 완료] 상태로 변경하시겠습니까?`;
            break;
        case 'cancel':
            endpoint = '/api/admin/orders/cancel';
            confirmMsg = `선택한 ${orderIds.length}건의 주문을 정말 취소하시겠습니까? 결제완료건은 환불 엔진이 호출됩니다.`;
            break;
        default:
            return;
    }

    if (!confirm(confirmMsg)) return;

    try {
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_ids: orderIds, reason: '관리자 일괄 처리' })
        });
        const data = await resp.json();

        if (resp.ok) {
            const successCount = data.success ? data.success.length : 0;
            const failedItems = data.failed || [];

            if (failedItems.length === 0) {
                customAlert(`성공적으로 ${successCount}건 처리가 완료되었습니다.`, 'success');
            } else {
                const failDetails = failedItems.map(f => `주문 #${f.order_id}: ${f.message}`).join('\n');
                alert(`[부분 처리 결과 안내]\n- 성공: ${successCount}건\n- 실패: ${failedItems.length}건\n\n실패 상세 사유:\n${failDetails}`);
            }

            selectedOrderIds.clear();
            updateSelectAllCheckboxState();
            await loadOrderSubTabCounts();
            await loadOrders();
        } else {
            customAlert(data.error || '일괄 요청 처리 실패', 'error');
        }
    } catch (err) {
        console.error('일괄 Command 실행 실패:', err);
        customAlert('요청 중 서버 오류가 발생했습니다.', 'error');
    }
}

// 8. 인라인 송장 일괄 저장
async function executeBatchSaveInlineTracking() {
    const items = [];
    document.querySelectorAll('.inline-tracking-input').forEach(input => {
        const oid = parseInt(input.dataset.orderId);
        const tracking = input.value.trim();
        const courierSelect = document.querySelector(`.inline-courier-select[data-order-id="${oid}"]`);
        const courier = courierSelect ? courierSelect.value : 'CJ대한통운';

        if (tracking) {
            items.push({ order_id: oid, carrier_code: courier, tracking_number: tracking });
        }
    });

    if (items.length === 0) {
        customAlert('저장할 운송장 번호가 입력된 행이 없습니다.', 'error');
        return;
    }

    try {
        const resp = await fetch('/api/admin/orders/batch-tracking', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ items })
        });
        const data = await resp.json();

        if (resp.ok) {
            const successCount = data.success ? data.success.length : 0;
            const failedItems = data.failed || [];
            if (failedItems.length === 0) {
                customAlert(`성공적으로 ${successCount}건의 송장이 저장되었습니다.`, 'success');
            } else {
                const failDetails = failedItems.map(f => `주문 #${f.order_id}: ${f.message}`).join('\n');
                alert(`[송장 저장 결과]\n- 성공: ${successCount}건\n- 실패: ${failedItems.length}건\n\n실패 상세:\n${failDetails}`);
            }
            await loadOrderSubTabCounts();
            await loadOrders();
        } else {
            customAlert(data.error || '송장 일괄 저장 실패', 'error');
        }
    } catch (err) {
        console.error('송장 일괄 저장 오류:', err);
        customAlert('송장 저장 요청 중 서버 오류가 발생했습니다.', 'error');
    }
}

function ordersGoPage(page) {
    ordersCurrentPage = page;
    loadOrders(null, page);
}

function filterOrders() {
    ordersCurrentPage = 1;
    loadOrders();
}

function resetOrderFilters() {
    ['order-status-filter', 'payment-status-filter', 'refund-status-filter', 'order-keyword-filter']
        .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    ordersCurrentPage = 1;
    loadOrders();
}

// 기존 하위 호환 호칭 유지
function switchOrderSubTab(pageKey) {
    switchOperationsPage(pageKey);
}

// 주문 상세 모달 및 환불 로직 보존
async function openOrderDetail(orderId) {
    try {
        const resp = await fetch(`/api/admin/orders/${orderId}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) { customAlert('주문 상세 정보를 불러오지 못했습니다.', 'error'); return; }
        const data = await resp.json();
        currentModalOrderData = data;
        const ord = data.order;
        const items = data.items || [];
        const notes = data.admin_notes || [];
        const timeline = data.timeline || [];

        const isShipped = ['SHIPPING', 'DELIVERED', 'CANCELLED'].includes(ord.order_status);

        const itemsHtml = items.map(it => {
            const remQty = it.quantity - it.cancelled_qty;
            const canRefund = remQty > 0 && !isShipped;
            return `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid #eee;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        ${canRefund ? `<input type="checkbox" class="refund-item-chk" data-item-id="${it.id}" data-max-qty="${remQty}" checked>` : ''}
                        <div>
                            <strong style="color:#2c3e50;">${it.product_name_snapshot}</strong> (${it.option_name_snapshot || '기본'})
                            <div style="font-size:0.8rem; color:#666;">
                                구매: ${it.quantity}개 | 취소: <span style="color:#c62828;">${it.cancelled_qty}개</span> | 환불가능: <strong>${remQty}개</strong>
                            </div>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div><strong>${(it.subtotal || 0).toLocaleString()}원</strong></div>
                        ${canRefund ? `
                            <div style="font-size:0.8rem; color:#555;">
                                환불 수량: <input type="number" class="refund-item-qty" data-item-id="${it.id}" value="${remQty}" min="1" max="${remQty}" style="width:50px; text-align:center; padding:2px;">
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');

        const notesHtml = notes.length > 0 ? notes.map(n => `
            <div style="background:#fff; border:1px solid #e0e0e0; padding:8px 12px; border-radius:6px; margin-bottom:6px; font-size:0.85rem;">
                <div style="display:flex; justify-content:space-between; color:#777; font-size:0.75rem; margin-bottom:3px;">
                    <span><strong>${n.admin_email}</strong></span><span>${n.created_at}</span>
                </div>
                <div style="color:#333;">${n.note}</div>
            </div>
        `).join('') : '<p style="font-size:0.85rem; color:#888; margin:0;">등록된 관리자 메모가 없습니다.</p>';

        const timelineHtml = timeline.map(t => `
            <div style="display:flex; gap:10px; font-size:0.8rem; padding:4px 0; border-bottom:1px dashed #eee;">
                <span style="color:#888; width:130px;">${t.time}</span>
                <strong style="color:#2c3e50; width:140px;">${t.event}</strong>
                <span style="color:#555;">${t.description}</span>
            </div>
        `).join('');

        const modalBodyHtml = `
            <div style="background:#faf8f5; border:1px solid #ebe6df; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <div>
                        <span style="font-size:0.8rem; color:#777;">주문번호</span>
                        <strong style="font-size:1.1rem; color:#2c3e50; margin-left:6px;">${ord.order_number}</strong>
                        <span style="font-size:0.8rem; color:#888; margin-left:8px;">(${ord.created_at})</span>
                    </div>
                    <div>
                        <span class="status-badge status-${ord.order_status}">${getOrderStatusKo(ord.order_status)}</span>
                        <span class="status-badge status-${ord.payment_status}" style="margin-left:4px;">${getPaymentStatusKo(ord.payment_status)}</span>
                    </div>
                </div>
                <div style="display:flex; gap:10px; align-items:center; border-top:1px solid #eee; padding-top:10px;">
                    <label style="font-size:0.85rem; font-weight:600; color:#444; margin:0;">주문/배송 상태 변경:</label>
                    <select id="modal-order-status-select" class="form-control" style="width:auto; padding:4px 10px; font-size:0.85rem;">
                        ${['PENDING', 'CONFIRMED', 'PREPARING', 'READY_TO_SHIP', 'SHIPPING', 'DELIVERED'].map(s =>
            `<option value="${s}" ${ord.order_status === s ? 'selected' : ''}>${getOrderStatusKo(s)}</option>`
        ).join('')}
                    </select>
                    <button type="button" onclick="submitUpdateOrderStatus(${ord.id}, this)" class="btn-action" style="background:#455a64; color:#fff; padding:4px 12px; font-size:0.8rem;">상태 변경 저장</button>
                </div>
            </div>

            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0; color:#2c3e50;">수령인 및 배송지 정보</h4>
                    ${isShipped ? `<span style="font-size:0.75rem; color:#d32f2f; font-weight:600;">출고 완료건은 배송지 수정 불가</span>` : ''}
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:8px;">
                    <div><label style="font-size:0.75rem; color:#666; display:block;">수령인 이름</label>
                    <input type="text" id="modal-addr-name" class="form-control" value="${ord.recipient_name || ''}" ${isShipped ? 'disabled' : ''} style="padding:4px 8px; font-size:0.85rem;"></div>
                    <div><label style="font-size:0.75rem; color:#666; display:block;">연락처</label>
                    <input type="text" id="modal-addr-phone" class="form-control" value="${ord.recipient_phone || ''}" ${isShipped ? 'disabled' : ''} style="padding:4px 8px; font-size:0.85rem;"></div>
                </div>
                <div style="display:grid; grid-template-columns: 100px 1fr; gap:10px; margin-bottom:8px;">
                    <div><label style="font-size:0.75rem; color:#666; display:block;">우편번호</label>
                    <input type="text" id="modal-addr-postal" class="form-control" value="${ord.postal_code || ''}" ${isShipped ? 'disabled' : ''} style="padding:4px 8px; font-size:0.85rem;"></div>
                    <div><label style="font-size:0.75rem; color:#666; display:block;">기본 주소</label>
                    <input type="text" id="modal-addr-address" class="form-control" value="${ord.address || ''}" ${isShipped ? 'disabled' : ''} style="padding:4px 8px; font-size:0.85rem;"></div>
                </div>
                <div style="margin-bottom:8px;"><label style="font-size:0.75rem; color:#666; display:block;">상세 주소</label>
                <input type="text" id="modal-addr-detail" class="form-control" value="${ord.address_detail || ''}" ${isShipped ? 'disabled' : ''} style="padding:4px 8px; font-size:0.85rem;"></div>
                <div style="margin-bottom:10px;"><label style="font-size:0.75rem; color:#666; display:block;">배송 메모</label>
                <input type="text" id="modal-addr-memo" class="form-control" value="${ord.delivery_memo || ''}" ${isShipped ? 'disabled' : ''} style="padding:4px 8px; font-size:0.85rem;"></div>
                ${!isShipped ? `<div style="text-align:right;"><button type="button" onclick="submitUpdateAddress(${ord.id}, this)" class="btn-action" style="background:#2e7d32; color:#fff; padding:4px 12px; font-size:0.8rem;">배송지 정보 수정 저장</button></div>` : ''}
            </div>

            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0 0 10px 0; color:#2c3e50;">배송 & 운송장 번호 관리</h4>
                <div style="display:flex; gap:8px; align-items:center;">
                    <select id="modal-courier-select" class="form-control" style="width:140px; padding:6px 10px; font-size:0.85rem;" ${isShipped ? 'disabled' : ''}>
                        ${['CJ대한통운', '우체국택배', '한진택배', '롯데택배', '로젠택배'].map(c =>
            `<option value="${c}" ${ord.courier_name === c ? 'selected' : ''}>${c}</option>`
        ).join('')}
                    </select>
                    <input type="text" id="modal-tracking-input" class="form-control" placeholder="운송장 번호 입력" value="${ord.tracking_number || ''}" style="flex:1; padding:6px 10px; font-size:0.85rem;" ${isShipped ? 'disabled' : ''}>
                    <button type="button" onclick="submitRegisterTracking(${ord.id}, this)" class="btn-action" style="background:${isShipped ? '#9e9e9e' : 'var(--admin-primary)'}; color:#fff; padding:6px 14px; font-size:0.85rem; font-weight:600;" ${isShipped ? 'disabled' : ''}>
                        운송장 등록 및 출고
                    </button>
                </div>
            </div>

            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0; color:#2c3e50;">상품 및 환불 관리</h4>
                    <span style="font-size:0.75rem; color:#2e7d32; font-weight:600;">관리자 환불 처리 권한 보유</span>
                </div>
                ${itemsHtml}
                <div style="text-align:right; font-size:1.1rem; color:#915a28; margin:10px 0;"><strong>총 결제금액: ${(ord.total_amount || 0).toLocaleString()}원</strong></div>
                ${isShipped ? `
                    <div style="background:#fafafa; padding:10px; border-radius:6px; border:1px solid #eee; color:#666; font-size:0.82rem; text-align:center;">
                        배송 중 / 배송 완료된 주문은 관리자 직접 환불이 제한됩니다.
                    </div>
                ` : `
                    <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:10px;">
                        <button type="button" onclick="openRefundConfirmModal(${ord.id}, false)" class="btn-action" style="background:#d32f2f; color:#fff; padding:6px 14px; font-size:0.85rem;">선택 상품 환불 미리보기 & 실행</button>
                        <button type="button" onclick="openRefundConfirmModal(${ord.id}, true)" class="btn-action" style="background:#b71c1c; color:#fff; padding:6px 14px; font-size:0.85rem;">전체 주문 취소/환불</button>
                    </div>
                `}
            </div>

            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px;">
                <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0 0 10px 0; color:#2c3e50;">관리자 메모</h4>
                <div style="display:flex; gap:8px; margin-bottom:12px;">
                    <input type="text" id="modal-new-note-input" class="form-control" placeholder="관리자 전용 메모 입력" style="flex:1; padding:6px 10px; font-size:0.85rem;">
                    <button type="button" onclick="submitAddOrderNote(${ord.id}, this)" class="btn-action" style="background:#455a64; color:#fff; padding:6px 14px; font-size:0.85rem;">메모 저장</button>
                </div>
                <div style="max-height:140px; overflow-y:auto; margin-bottom:12px;">${notesHtml}</div>
                <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:12px 0 8px 0; color:#2c3e50; border-top:1px solid #eee; padding-top:10px;">타임라인</h4>
                <div style="max-height:140px; overflow-y:auto; background:#fafafa; padding:8px 12px; border-radius:6px; border:1px solid #eee;">${timelineHtml}</div>
            </div>
        `;

        document.getElementById('admin-order-modal-body').innerHTML = modalBodyHtml;
        openModal('orderDetailModal');
    } catch (err) {
        console.error(err);
        customAlert('주문 모달을 여는 중 오류가 발생했습니다.', 'error');
    }
}

async function submitUpdateOrderStatus(orderId, btnEl) {
    const targetStatus = document.getElementById('modal-order-status-select').value;
    if (!confirm(`주문 상태를 [${targetStatus}](으)로 변경하시겠습니까?`)) return;
    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/status`, {
            method: 'PATCH',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_status: targetStatus, reason: '관리자 콘솔 직접 수정' })
        });
        const data = await resp.json();
        if (resp.ok) { customAlert(data.message || '상태 변경 완료', 'success'); openOrderDetail(orderId); loadOrders(); loadOrderSubTabCounts(); }
        else customAlert(data.error || '상태 변경 실패', 'error');
    } catch (err) { console.error(err); customAlert('주문 상태 변경 요청 실패', 'error'); }
    finally { btnEl.disabled = false; }
}

async function submitRegisterTracking(orderId, btnEl) {
    const courierName = document.getElementById('modal-courier-select').value;
    const trackingNumber = document.getElementById('modal-tracking-input').value.trim();
    if (!trackingNumber) { customAlert('운송장 번호를 입력해 주세요.', 'error'); return; }
    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/shipping`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ courier_name: courierName, tracking_number: trackingNumber })
        });
        const data = await resp.json();
        if (resp.ok) { customAlert(data.message || '운송장 등록 완료', 'success'); openOrderDetail(orderId); loadOrders(); loadOrderSubTabCounts(); }
        else customAlert(data.error || '운송장 등록 실패', 'error');
    } catch (err) { console.error(err); customAlert('운송장 등록 요청 실패', 'error'); }
    finally { btnEl.disabled = false; }
}

async function submitUpdateAddress(orderId, btnEl) {
    const payload = {
        recipient_name: document.getElementById('modal-addr-name').value.trim(),
        recipient_phone: document.getElementById('modal-addr-phone').value.trim(),
        postal_code: document.getElementById('modal-addr-postal').value.trim(),
        address: document.getElementById('modal-addr-address').value.trim(),
        address_detail: document.getElementById('modal-addr-detail').value.trim(),
        delivery_memo: document.getElementById('modal-addr-memo').value.trim()
    };
    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/address`, {
            method: 'PATCH',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (resp.ok) { customAlert(data.message || '배송지 수정 완료', 'success'); openOrderDetail(orderId); }
        else customAlert(data.error || '배송지 수정 실패', 'error');
    } catch (err) { console.error(err); customAlert('배송지 수정 요청 실패', 'error'); }
    finally { btnEl.disabled = false; }
}

async function submitAddOrderNote(orderId, btnEl) {
    const input = document.getElementById('modal-new-note-input');
    const note = input.value.trim();
    if (!note) { customAlert('메모 내용을 입력해 주세요.', 'error'); return; }
    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/notes`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ note })
        });
        const data = await resp.json();
        if (resp.ok) { input.value = ''; openOrderDetail(orderId); }
        else customAlert(data.error || '메모 저장 실패', 'error');
    } catch (err) { console.error(err); customAlert('메모 저장 요청 실패', 'error'); }
    finally { btnEl.disabled = false; }
}

async function openRefundConfirmModal(orderId, isFullRefund = false) {
    if (!currentModalOrderData) return;
    document.getElementById('refund-target-order-id').value = orderId;
    const itemsToRefund = [];
    if (isFullRefund) {
        (currentModalOrderData.items || []).forEach(it => {
            const remQty = it.quantity - it.cancelled_qty;
            if (remQty > 0) itemsToRefund.push({ order_item_id: it.id, quantity: remQty });
        });
    } else {
        document.querySelectorAll('.refund-item-chk:checked').forEach(chk => {
            const itemId = parseInt(chk.dataset.itemId);
            const qtyInput = document.querySelector(`.refund-item-qty[data-item-id="${itemId}"]`);
            const qty = qtyInput ? parseInt(qtyInput.value) : 1;
            if (qty > 0) itemsToRefund.push({ order_item_id: itemId, quantity: qty });
        });
    }
    if (itemsToRefund.length === 0) { customAlert('환불할 수 있는 상품이 없거나 선택되지 않았습니다.', 'error'); return; }

    const previewBody = document.getElementById('refund-preview-body');
    previewBody.innerHTML = '<p>환불 계산 중...</p>';
    openModal('adminRefundConfirmModal');

    try {
        const resp = await fetch(`/api/admin/orders/${orderId}/refund/preview`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: itemsToRefund })
        });
        const data = await resp.json();
        if (resp.ok && data.preview) {
            const p = data.preview;
            previewBody.innerHTML = `
                <div><strong>환불 대상 품목 수:</strong> ${p.items.length}개</div>
                <div><strong>상품 금액 합계:</strong> ${(p.items_subtotal || 0).toLocaleString()}원</div>
                <div><strong>차감 배송비:</strong> ${(p.deducted_shipping_fee || 0).toLocaleString()}원</div>
                <div style="font-size:1.1rem; color:#c62828; margin-top:6px;"><strong>최종 환불 예정: ${(p.calculated_refund_amount || 0).toLocaleString()}원</strong></div>
            `;
            previewBody.dataset.refundItemsJson = JSON.stringify(itemsToRefund);
        } else {
            previewBody.innerHTML = `<p style="color:#d32f2f;">${data.error || '환불 계산 실패'}</p>`;
        }
    } catch (err) { console.error(err); previewBody.innerHTML = '<p style="color:#d32f2f;">오류가 발생했습니다.</p>'; }
}

async function executeFinalAdminRefund(btnEl) {
    const orderId = document.getElementById('refund-target-order-id').value;
    const previewBody = document.getElementById('refund-preview-body');
    const itemsJson = previewBody.dataset.refundItemsJson;
    const reasonCode = document.getElementById('refund-reason-code').value;
    const reasonCustom = document.getElementById('refund-reason-custom').value.trim();
    if (!itemsJson) { customAlert('환불 상품 정보가 올바르지 않습니다.', 'error'); return; }
    const reason = reasonCustom ? `[${reasonCode}] ${reasonCustom}` : reasonCode;
    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/refund`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: JSON.parse(itemsJson), reason_code: reasonCode, reason })
        });
        const data = await resp.json();
        if (resp.ok) {
            customAlert(data.message || '환불이 성공적으로 처리되었습니다.', 'success');
            closeModal('adminRefundConfirmModal');
            closeModal('orderDetailModal');
            loadOrderSubTabCounts();
            loadOrders();
            loadDashboardMetrics();
        } else customAlert(data.error || '환불 처리 실패', 'error');
    } catch (err) { console.error(err); customAlert('환불 요청 중 오류 발생', 'error'); }
    finally { btnEl.disabled = false; }
}
