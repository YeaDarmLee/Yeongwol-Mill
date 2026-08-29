/* orders.js: Declarative Config 기반 라우트 뷰, Stale Response 방어, 인라인 송장 및 배치 처리 스크립트 */

if (typeof escapeHtml !== 'function') {
    window.escapeHtml = function (str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    };
}

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
        toolbarButtons: ['exportExcel', 'importExcel', 'saveTracking', 'ship'],
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

    // [0ms 즉시 스켈레톤 렌더링] 이전 리스트 잔상 즉시 삭제 및 스켈레톤 행 렌더링
    renderSkeletonTableRows();
    const countBadge = document.getElementById('orders-page-count-badge');
    if (countBadge) countBadge.innerText = '...';

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

    renderBatchActionButtons(config.toolbarButtons);

    // 주문 목록 로드 & Badge 업데이트 (병렬 처리하여 딜레이 제거)
    ordersCurrentPage = 1;
    loadOrderSubTabCounts();
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
        } else if (type === 'exportExcel') {
            buttonsHtml += `<button class="btn-action" style="background:#1b5e20; color:#fff;" onclick="exportOrdersCSV('shipping')"><i class="fa-solid fa-file-excel" style="margin-right:4px;"></i> 송장 작성용 엑셀 다운로드</button>`;
        } else if (type === 'importExcel') {
            buttonsHtml += `<button class="btn-action" style="background:#004d40; color:#fff;" onclick="importTrackingCSV()"><i class="fa-solid fa-file-arrow-up" style="margin-right:4px;"></i> 운송장 엑셀 일괄 업로드</button>`;
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

function renderSkeletonTableRows(rowCount = 5) {
    const tbody = document.getElementById('orders-tbody');
    if (!tbody) return;
    let html = '';
    for (let i = 0; i < rowCount; i++) {
        html += `
            <tr class="skeleton-row">
                <td style="text-align:center;"><div class="skeleton-box" style="width:18px; height:18px; margin:auto; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:30px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:110px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:90px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:160px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:75px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:70px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:70px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td><div class="skeleton-box" style="width:110px; height:18px; background:#eee; border-radius:3px;"></div></td>
                <td style="text-align:center;"><div class="skeleton-box" style="width:65px; height:18px; margin:auto; background:#eee; border-radius:3px;"></div></td>
            </tr>
        `;
    }
    tbody.innerHTML = html;
}

// 5. 주문 데이터 로드 & Stale Response Race Condition 방어
async function loadOrders(activeConfig = null, page = null) {
    if (page !== null) ordersCurrentPage = page;
    const requestToken = ++currentRequestToken; // 토큰 증가

    const config = activeConfig || ORDER_PAGE_CONFIG[currentOrderSubTab] || CS_PAGE_CONFIG[currentOrderSubTab] || ORDER_PAGE_CONFIG['all'];

    // 페이지 / 탭 전환 즉시 스켈레톤 UI 표출
    renderSkeletonTableRows();

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

                // 주문 상품 요약 텍스트 정밀 조율 (객체 / 문자열 대응)
                let prodSummaryText = '';
                const rawSummary = ord.product_summary;

                if (typeof rawSummary === 'object' && rawSummary !== null) {
                    if (rawSummary.summary_text) {
                        prodSummaryText = rawSummary.summary_text;
                    } else if (rawSummary.first_product_name) {
                        const firstQty = (rawSummary.items && rawSummary.items[0]) ? rawSummary.items[0].quantity : 1;
                        prodSummaryText = rawSummary.extra_item_count > 0
                            ? `${rawSummary.first_product_name} 외 ${rawSummary.extra_item_count}건`
                            : `${rawSummary.first_product_name} ${firstQty}개`;
                    }
                } else if (typeof rawSummary === 'string' && rawSummary.trim() !== '') {
                    prodSummaryText = rawSummary;
                }

                if (!prodSummaryText && ord.items && ord.items.length > 0) {
                    const first = ord.items[0];
                    const name = first.product_name_snapshot || first.product_name || '상품';
                    prodSummaryText = `${name} ${first.quantity || 1}개`;
                    if (ord.items.length > 1) {
                        prodSummaryText += ` 외 ${ord.items.length - 1}건`;
                    }
                }

                if (!prodSummaryText) {
                    prodSummaryText = ord.order_name || '상품 정보 없음';
                }

                // 전체 상품 툴팁 HTML 구성
                let tooltipItemsHtml = '';
                const itemsArray = ord.items || (typeof ord.product_summary === 'object' && ord.product_summary ? ord.product_summary.items : []);

                if (itemsArray && itemsArray.length > 0) {
                    tooltipItemsHtml = itemsArray.map((it, idx) => {
                        const pName = escapeHtml(it.product_name_snapshot || it.product_name || '상품');
                        const pOpt = (it.option_name_snapshot || it.option_name) ? ` (${escapeHtml(it.option_name_snapshot || it.option_name)})` : '';
                        const pQty = it.quantity || 1;
                        const pPaid = (it.item_paid_amount || (it.final_unit_price * pQty) || (it.unit_price * pQty) || 0).toLocaleString();
                        return `
                            <div class="tooltip-item-row">
                                <span><strong>${idx + 1}.</strong> ${pName}${pOpt}</span>
                                <span style="color:#ffe0b2; font-weight:600; margin-left:12px; white-space:nowrap;">${pQty}개 (${pPaid}원)</span>
                            </div>
                        `;
                    }).join('');
                } else {
                    tooltipItemsHtml = `<div style="color:#aaa;">${escapeHtml(prodSummaryText)}</div>`;
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
                        <td>
                            <strong>${escapeHtml(ord.recipient_name || ord.guest_name || '구매자')}</strong>
                            <div style="font-size:0.78rem; color:#666;">${escapeHtml(ord.recipient_phone || '-')}</div>
                        </td>
                        <td>
                            <div class="order-product-hover-wrapper">
                                <div style="font-weight:600; color:#2c3e50; font-size:0.85rem; display:inline-flex; align-items:center; gap:4px;">
                                    ${escapeHtml(prodSummaryText)}
                                    <i class="fa-solid fa-circle-info" style="font-size:0.75rem; color:#a0aec0;"></i>
                                </div>
                                <div class="product-tooltip-card">
                                    <div style="font-weight:700; font-size:0.85rem; border-bottom:1px solid rgba(255,255,255,0.2); padding-bottom:4px; margin-bottom:6px; color:#ffe0b2; display:flex; justify-content:space-between; align-items:center;">
                                        <span><i class="fa-solid fa-basket-shopping" style="margin-right:4px;"></i> 전체 주문 상품 상세</span>
                                        <span style="font-size:0.75rem; color:#e2e8f0; font-weight:normal;">총 ${itemsArray ? itemsArray.length : 1}개 품목</span>
                                    </div>
                                    ${tooltipItemsHtml}
                                </div>
                            </div>
                        </td>
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

    const confirmed = await customConfirm(confirmMsg, '일괄 변경 확인');
    if (!confirmed) return;

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
                const failDetails = failedItems.map(f => `주문 #${f.order_id}: ${f.message}`).join(', ');
                customAlert(`성공: ${successCount}건 / 실패: ${failedItems.length}건 (${failDetails})`, 'warning');
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

        const rawStatus = (ord.order_status || '').trim();
        const st = rawStatus.toUpperCase();

        const isShipped = ['SHIPPING', 'DELIVERED', 'CANCELLED'].includes(st);
        const isReadyToShip = ['READY_TO_SHIP', 'READY_FOR_FULFILLMENT', 'PREPARING_SHIPMENT', '배송 준비중', '배송준비중'].includes(st) || ['배송 준비중', '배송준비중'].includes(rawStatus);
        const isShippingOrDelivered = ['SHIPPING', 'DELIVERED', 'SHIPPED', 'DELIVERING', '배송중', '배송 완료', '배송완료', '출고완료'].includes(st) || ['배송중', '배송 완료', '배송완료', '출고완료'].includes(rawStatus);

        const itemsHtml = items.map(it => {
            return `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #f0f0f0;">
                    <div>
                        <strong style="color:#2c3e50; font-size:0.92rem;">${escapeHtml(it.product_name_snapshot)}</strong> 
                        <span style="color:#777; font-size:0.85rem;">(${escapeHtml(it.option_name_snapshot || '기본')})</span>
                        <div style="font-size:0.83rem; color:#666; margin-top:2px;">
                            주문 수량: <strong style="color:#333;">${it.quantity}개</strong> ${it.cancelled_qty > 0 ? `<span style="color:#b84a4a; margin-left:6px;">(취소/환불: ${it.cancelled_qty}개)</span>` : ''}
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:0.95rem; font-weight:700; color:#2c3e50;">${(it.subtotal || 0).toLocaleString()}원</div>
                        <div style="font-size:0.78rem; color:#888; margin-top:2px;">(개당 ${(it.unit_price || 0).toLocaleString()}원)</div>
                    </div>
                </div>
            `;
        }).join('');

        const notesHtml = notes.length > 0 ? notes.map(n => `
            <div style="background:#fff; border:1px solid #e0e0e0; padding:8px 12px; border-radius:6px; margin-bottom:6px; font-size:0.85rem;">
                <div style="display:flex; justify-content:space-between; color:#777; font-size:0.75rem; margin-bottom:3px;">
                    <span><strong>${escapeHtml(n.admin_email || '관리자')}</strong></span><span>${n.created_at || ''}</span>
                </div>
                <div style="color:#333;">${escapeHtml(n.note || '')}</div>
            </div>
        `).join('') : '<p style="font-size:0.85rem; color:#888; margin:0;">등록된 관리자 메모가 없습니다.</p>';

        const timelineHtml = timeline.map(t => `
            <div style="display:flex; gap:10px; font-size:0.8rem; padding:4px 0; border-bottom:1px dashed #eee;">
                <span style="color:#888; width:130px;">${t.time || ''}</span>
                <strong style="color:#2c3e50; width:140px;">${t.event || ''}</strong>
                <span style="color:#555;">${t.description || ''}</span>
            </div>
        `).join('');

        // 1. 배송 및 운송장 번호 관리 섹션 HTML
        let shippingSectionHtml = '';
        if (isReadyToShip) {
            shippingSectionHtml = `
                <form onsubmit="submitShipment(event, ${ord.id})">
                    <div style="display:flex; gap:8px; align-items:center;">
                        <select id="modal-carrier-code" class="form-control" style="width:140px; padding:7px 10px; font-size:0.85rem;" required>
                            <option value="CJ_LOGISTICS" ${ord.courier_name === 'CJ대한통운' ? 'selected' : ''}>CJ대한통운</option>
                            <option value="EPOST" ${ord.courier_name === '우체국택배' ? 'selected' : ''}>우체국택배</option>
                            <option value="HANJIN" ${ord.courier_name === '한진택배' ? 'selected' : ''}>한진택배</option>
                            <option value="LOTTE" ${ord.courier_name === '롯데택배' ? 'selected' : ''}>롯데택배</option>
                        </select>
                        <input type="text" id="modal-tracking-number" class="form-control" placeholder="운송장 번호 입력 (영문/숫자)" value="${ord.tracking_number || ''}" required style="flex:1; padding:7px 10px; font-size:0.85rem;">
                        <button type="submit" id="btn-submit-shipment" class="btn-action btn-action-primary" style="padding:7px 16px; font-size:0.85rem; font-weight:600; display:flex; align-items:center; gap:5px;">
                            <i class="fa-solid fa-truck-fast"></i> 운송장 등록 및 출고
                        </button>
                    </div>
                    <div style="font-size:0.78rem; color:#666; margin-top:6px; display:flex; align-items:center; gap:4px;">
                        <i class="fa-solid fa-circle-info" style="color:var(--admin-primary, #C59B27);"></i> 운송장 등록과 동시에 주문이 '배송중' 상태로 전환됩니다.
                    </div>
                </form>
            `;
        } else if (isShippingOrDelivered) {
            const courierName = escapeHtml(ord.courier_name || '택배사');
            const trackingNum = escapeHtml(ord.tracking_number || '미등록');
            let trackingUrl = '#';
            if (ord.courier_name && ord.courier_name.includes('우체국')) {
                trackingUrl = `https://service.epost.go.kr/trace.RetrieveDomRレースTraceList.comm?sid1=${trackingNum}`;
            } else if (ord.courier_name && ord.courier_name.includes('한진')) {
                trackingUrl = `https://www.hanjin.co.kr/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038&wblnum=${trackingNum}`;
            } else if (ord.courier_name && ord.courier_name.includes('롯데')) {
                trackingUrl = `https://www.lotteglogis.com/home/reservation/tracking/linkView?InvNo=${trackingNum}`;
            } else {
                trackingUrl = `https://www.cjlogistics.com/ko/tool/parcel/tracking?gnbInvcNo=${trackingNum}`;
            }

            shippingSectionHtml = `
                <div style="background:#faf8f5; border:1px solid #f0e6d8; padding:12px 16px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:0.78rem; color:#888; display:block;">등록된 택배사 및 운송장</span>
                        <strong style="font-size:0.95rem; color:#2c3e50;">${courierName} ${trackingNum}</strong>
                    </div>
                    ${ord.tracking_number ? `<a href="${trackingUrl}" target="_blank" class="btn-action btn-action-secondary" style="font-size:0.8rem; text-decoration:none;"><i class="fa-solid fa-arrow-up-right-from-square"></i> 실시간 배송 추적</a>` : ''}
                </div>
            `;
        } else {
            shippingSectionHtml = `
                <div style="background:#faf8f5; border:1px solid #f0e6d8; padding:10px 14px; border-radius:8px; font-size:0.83rem; color:#666;">
                    <i class="fa-solid fa-circle-info" style="color:var(--admin-primary, #C59B27); margin-right:4px;"></i> [배송 준비중] 단계에서 운송장 번호 등록 및 출고가 가능합니다.
                </div>
            `;
        }

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
                    <button type="button" onclick="submitUpdateOrderStatus(${ord.id}, this)" class="btn-action btn-action-primary" style="padding:4px 12px; font-size:0.8rem;">상태 변경 저장</button>
                </div>
            </div>

            <!-- 수령인 및 배송지 정보 카드 (모달 수정 지원) -->
            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px dashed #eee; padding-bottom:8px;">
                    <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0; color:#2c3e50; display:flex; align-items:center; gap:6px;">
                        <i class="fa-solid fa-location-dot" style="color:var(--admin-primary, #C59B27);"></i> 수령인 및 배송지 정보
                    </h4>
                    ${!isShipped ? `
                        <button type="button" onclick="openShippingEditModal(${ord.id})" class="btn-action btn-action-secondary" style="padding:4px 12px; font-size:0.8rem; font-weight:600; display:flex; align-items:center; gap:5px;">
                            <i class="fa-solid fa-pen-to-square"></i> 배송지 수정
                        </button>
                    ` : `
                        <span style="font-size:0.78rem; color:#b84a4a; font-weight:600; display:flex; align-items:center; gap:4px;">
                            <i class="fa-solid fa-lock"></i> 출고 진행 중/완료건은 배송지 수정 불가
                        </span>
                    `}
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:8px; background:#faf8f5; padding:12px; border-radius:6px; border:1px solid #f0e6d8;">
                    <div><span style="font-size:0.75rem; color:#888; display:block;">수령인 이름</span>
                        <strong style="font-size:0.9rem; color:#333;">${escapeHtml(ord.recipient_name || ord.guest_name || '구매자')}</strong>
                    </div>
                    <div><span style="font-size:0.75rem; color:#888; display:block;">연락처</span>
                        <strong style="font-size:0.9rem; color:#333;">${escapeHtml(ord.recipient_phone || ord.guest_phone || '-')}</strong>
                    </div>
                </div>
                <div style="background:#faf8f5; padding:12px; border-radius:6px; border:1px solid #f0e6d8; margin-bottom:8px;">
                    <span style="font-size:0.75rem; color:#888; display:block;">배송지 주소</span>
                    <div style="font-size:0.88rem; font-weight:600; color:#333; margin-top:2px;">
                        <span style="background:#e0d6c8; color:#4a3b32; font-size:0.75rem; padding:1px 6px; border-radius:3px; font-weight:700; margin-right:4px;">[${escapeHtml(ord.postal_code || '00000')}]</span>
                        ${escapeHtml(ord.address || '')} ${escapeHtml(ord.address_detail || '')}
                    </div>
                </div>
                <div style="background:#faf8f5; padding:10px 12px; border-radius:6px; border:1px solid #f0e6d8;">
                    <span style="font-size:0.75rem; color:#888; display:block;">배송 요청사항 / 메모</span>
                    <div style="font-size:0.85rem; color:#555; margin-top:2px;">
                        ${escapeHtml(ord.delivery_memo || '등록된 배송 메모가 없습니다.')}
                    </div>
                </div>
            </div>

            <!-- 배송 & 운송장 번호 관리 카드 -->
            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0 0 12px 0; color:#2c3e50; display:flex; align-items:center; gap:6px;">
                    <i class="fa-solid fa-truck-fast" style="color:var(--admin-primary, #C59B27);"></i> 배송 & 운송장 번호 관리
                </h4>
                ${shippingSectionHtml}
            </div>

            <!-- 주문 상품 목록 카드 (환불 조작 버튼은 하단 푸터로 이동) -->
            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; border-bottom:1px dashed #eee; padding-bottom:8px;">
                    <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0; color:#2c3e50;">주문 상품 목록</h4>
                    <span style="font-size:0.75rem; color:#4a6b52; font-weight:600;">관리자 환불 처리 권한 보유</span>
                </div>
                ${itemsHtml}
                <div style="text-align:right; font-size:1.1rem; color:#915a28; margin:10px 0 0 0;"><strong>총 결제금액: ${(ord.total_amount || 0).toLocaleString()}원</strong></div>
            </div>

            <!-- 관리자 메모 & 타임라인 카드 -->
            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px;">
                <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0 0 10px 0; color:#2c3e50;">관리자 메모</h4>
                <div style="display:flex; gap:8px; margin-bottom:12px;">
                    <input type="text" id="modal-new-note-input" class="form-control" placeholder="관리자 전용 메모 입력" style="flex:1; padding:6px 10px; font-size:0.85rem;">
                    <button type="button" onclick="submitAddOrderNote(${ord.id}, this)" class="btn-action btn-action-primary" style="padding:6px 14px; font-size:0.85rem;">메모 저장</button>
                </div>
                <div style="max-height:140px; overflow-y:auto; margin-bottom:12px;">${notesHtml}</div>
                <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:12px 0 8px 0; color:#2c3e50; border-top:1px solid #eee; padding-top:10px;">타임라인</h4>
                <div style="max-height:140px; overflow-y:auto; background:#fafafa; padding:8px 12px; border-radius:6px; border:1px solid #eee;">${timelineHtml}</div>
            </div>
        `;

        document.getElementById('admin-order-modal-body').innerHTML = modalBodyHtml;

        // 모달 푸터 버튼 구성 (v2.2 스마트 액션 매트릭스 7단계 적용)
        const footerEl = document.getElementById('admin-order-modal-footer');
        if (footerEl) {
            let footerHtml = '';
            const latestReq = (data.refund_requests || [])[0];
            const isReconcileReq = latestReq && latestReq.status === 'RECONCILE_REQUIRED';
            const payStatus = ord.payment_status;

            if (payStatus === 'REFUNDED') {
                footerHtml = `<span style="font-size:0.85rem; color:#4a6b52; font-weight:700; margin-right:auto;"><i class="fa-solid fa-circle-check"></i> 취소 및 전액 환불 완료 건</span>`;
            } else if (isReconcileReq) {
                footerHtml = `
                    <button type="button" onclick="executeReconcileRefund(${ord.id}, this)" class="btn-action btn-action-danger" style="padding:7px 16px; font-size:0.85rem; font-weight:600; display:inline-flex; align-items:center; gap:5px;">
                        <i class="fa-solid fa-triangle-exclamation"></i> ⚠️ PG 환불 상태 재대조
                    </button>
                `;
            } else if (isShippingOrDelivered && !isReadyToShip) {
                footerHtml = `
                    <button type="button" onclick="customAlert('반품/교환 CS 관리 페이지로 이동합니다.', 'info')" class="btn-action btn-action-secondary" style="padding:7px 16px; font-size:0.85rem; font-weight:600; display:inline-flex; align-items:center; gap:5px;">
                        <i class="fa-solid fa-headset"></i> 반품/교환 CS 접수
                    </button>
                `;
            } else if (payStatus === 'PARTIALLY_REFUNDED') {
                footerHtml = `
                    <button type="button" onclick="openRefundConfirmModal(${ord.id})" class="btn-action btn-action-danger" style="padding:7px 16px; font-size:0.85rem; font-weight:600; display:inline-flex; align-items:center; gap:5px;">
                        <i class="fa-solid fa-file-invoice-dollar"></i> 환불 접수
                    </button>
                `;
            } else {
                footerHtml = `
                    <button type="button" onclick="openRefundConfirmModal(${ord.id})" class="btn-action btn-action-danger" style="padding:7px 16px; font-size:0.85rem; font-weight:600; display:inline-flex; align-items:center; gap:5px;">
                        <i class="fa-solid fa-ban"></i> 주문 취소
                    </button>
                `;
            }
            footerHtml += `<button onclick="closeModal('orderDetailModal')" class="btn-action btn-action-secondary" style="padding:7px 20px;">닫기</button>`;
            footerEl.innerHTML = footerHtml;
        }

        openModal('orderDetailModal');
    } catch (err) {
        console.error(err);
        customAlert('주문 모달을 여는 중 오류가 발생했습니다.', 'error');
    }
}

async function submitUpdateOrderStatus(orderId, btnEl) {
    const targetStatus = document.getElementById('modal-order-status-select').value;
    const confirmed = await customConfirm(`주문 상태를 [${getOrderStatusKo(targetStatus)}](으)로 변경하시겠습니까?`, '주문 상태 변경 확인');
    if (!confirmed) return;
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

/**
 * 배송지 정보 수정 모달 열기
 */
function openShippingEditModal(orderId) {
    if (!currentModalOrderData || !currentModalOrderData.order) return;
    const ord = currentModalOrderData.order;

    const elId = document.getElementById('shipping-edit-order-id');
    if (elId) elId.value = orderId;

    const elName = document.getElementById('shipping-edit-name');
    if (elName) elName.value = ord.recipient_name || ord.guest_name || '';

    const elPhone = document.getElementById('shipping-edit-phone');
    if (elPhone) elPhone.value = ord.recipient_phone || ord.guest_phone || '';

    const elPostal = document.getElementById('shipping-edit-postal');
    if (elPostal) elPostal.value = ord.postal_code || '';

    const elAddress = document.getElementById('shipping-edit-address');
    if (elAddress) elAddress.value = ord.address || '';

    const elDetail = document.getElementById('shipping-edit-detail');
    if (elDetail) elDetail.value = ord.address_detail || '';

    const elMemo = document.getElementById('shipping-edit-memo');
    if (elMemo) elMemo.value = ord.delivery_memo || '';

    const elReason = document.getElementById('shipping-edit-reason-type');
    if (elReason) elReason.value = 'CUSTOMER_REQUEST';

    const elReasonDetail = document.getElementById('shipping-edit-reason-detail');
    if (elReasonDetail) elReasonDetail.value = '고객 요청에 의한 배송지 주소 변경';

    openModal('shippingEditModal');
}

/**
 * 배송지 정보 수정 제출
 */
async function submitShippingEdit(event) {
    if (event) event.preventDefault();
    const orderId = document.getElementById('shipping-edit-order-id').value;
    const btnSubmit = document.getElementById('btn-shipping-edit-submit');

    const name = document.getElementById('shipping-edit-name').value.trim();
    const phone = document.getElementById('shipping-edit-phone').value.trim();
    const postal = document.getElementById('shipping-edit-postal').value.trim();
    const address = document.getElementById('shipping-edit-address').value.trim();
    const detail = document.getElementById('shipping-edit-detail').value.trim();
    const memo = document.getElementById('shipping-edit-memo').value.trim();
    const reasonType = document.getElementById('shipping-edit-reason-type').value;
    const reasonDetail = document.getElementById('shipping-edit-reason-detail').value.trim();

    if (!name || !phone || !postal || !address || !reasonDetail) {
        customAlert('필수 항목 및 배송지 변경 사유를 입력해 주세요.', 'error');
        return;
    }

    try {
        if (btnSubmit) btnSubmit.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/address`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${adminToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                recipient_name: name,
                recipient_phone: phone,
                postal_code: postal,
                address: address,
                address_detail: detail,
                delivery_memo: memo,
                reason_type: reasonType,
                reason_detail: reasonDetail
            })
        });

        const data = await resp.json();
        if (resp.ok) {
            customAlert(data.message || '배송지 정보가 수정되었습니다.', 'success');
            closeModal('shippingEditModal');
            await openOrderDetail(orderId);
        } else {
            customAlert(data.error || '배송지 수정 실패', 'error');
        }
    } catch (err) {
        console.error(err);
        customAlert('배송지 정보 수정 요청 중 오류 발생', 'error');
    } finally {
        if (btnSubmit) btnSubmit.disabled = false;
    }
}

/**
 * 단건 운송장 번호 등록 및 출고 승인
 */
async function submitShipment(event, orderId) {
    if (event) event.preventDefault();
    const carrierSelect = document.getElementById('modal-carrier-code');
    const trackingInput = document.getElementById('modal-tracking-number');
    const carrierCode = carrierSelect ? carrierSelect.value : 'CJ_LOGISTICS';
    const trackingNumber = trackingInput ? trackingInput.value.trim() : '';
    const btnSubmit = document.getElementById('btn-submit-shipment');

    if (!trackingNumber) {
        customAlert('운송장 번호를 입력해 주세요.', 'error');
        return;
    }

    try {
        if (btnSubmit) btnSubmit.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/ship`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${adminToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                carrier_code: carrierCode,
                tracking_number: trackingNumber
            })
        });

        const data = await resp.json();
        if (resp.ok) {
            customAlert(data.message || '운송장이 성공적으로 등록되었습니다.', 'success');
            await openOrderDetail(orderId);
            await loadOrders();
            await loadOrderSubTabCounts();
        } else {
            customAlert(data.error || '운송장 등록 실패', 'error');
        }
    } catch (err) {
        console.error(err);
        customAlert('운송장 등록 요청 중 오류가 발생했습니다.', 'error');
    } finally {
        if (btnSubmit) btnSubmit.disabled = false;
    }
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

let previewDebounceTimer = null;

async function openRefundConfirmModal(orderId) {
    if (!currentModalOrderData) return;
    document.getElementById('refund-target-order-id').value = orderId;
    document.getElementById('refund-preview-token').value = '';

    const items = currentModalOrderData.items || [];
    const hasShipped = items.some(it => (it.shipped_qty || 0) > 0);
    const radFull = document.getElementById('refund-scope-full');
    const radPartial = document.getElementById('refund-scope-partial');
    const warnMsg = document.getElementById('refund-scope-warning-msg');

    if (hasShipped) {
        radFull.disabled = true;
        radFull.checked = false;
        radPartial.checked = true;
        if (warnMsg) warnMsg.style.display = 'block';
    } else {
        radFull.disabled = false;
        radFull.checked = true;
        radPartial.checked = false;
        if (warnMsg) warnMsg.style.display = 'none';
    }

    renderRefundItemsSelectionTable(items);
    openModal('adminRefundConfirmModal');
    handleRefundScopeChange(hasShipped ? 'PARTIAL' : 'FULL');
}

function renderRefundItemsSelectionTable(items) {
    const container = document.getElementById('refund-items-selection-container');
    if (!container) return;
    let html = `
        <table style="width:100%; font-size:0.82rem; border-collapse:collapse;">
            <thead>
                <tr style="background:#f5f5f5; border-bottom:1px solid #ddd;">
                    <th style="padding:6px; text-align:left;">상품명</th>
                    <th style="padding:6px; text-align:center; width:70px;">주문수량</th>
                    <th style="padding:6px; text-align:center; width:90px;">환불수량</th>
                </tr>
            </thead>
            <tbody>
    `;
    items.forEach(it => {
        const remQty = Math.max(0, it.quantity - (it.shipped_qty || 0) - (it.cancelled_qty || 0));
        html += `
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:6px;">${escapeHtml(it.product_name_snapshot)}</td>
                <td style="padding:6px; text-align:center;">${it.quantity}개</td>
                <td style="padding:6px; text-align:center;">
                    <input type="number" class="modal-refund-item-qty" data-item-id="${it.id}" min="0" max="${remQty}" value="${remQty}" onchange="triggerDebouncedPreview()" style="width:55px; padding:3px 5px; text-align:center; font-size:0.82rem;">
                </td>
            </tr>
        `;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function handleRefundScopeChange(scope) {
    const container = document.getElementById('refund-items-selection-container');
    if (container) {
        container.style.display = scope === 'PARTIAL' ? 'block' : 'none';
    }
    triggerDebouncedPreview();
}

function triggerDebouncedPreview() {
    if (previewDebounceTimer) clearTimeout(previewDebounceTimer);
    previewDebounceTimer = setTimeout(() => {
        fetchRefundPreview();
    }, 300);
}

async function fetchRefundPreview() {
    const orderId = document.getElementById('refund-target-order-id').value;
    const scope = document.querySelector('input[name="refund_scope"]:checked')?.value || 'FULL';
    const previewBody = document.getElementById('refund-preview-body');
    const btnExecute = document.getElementById('btn-execute-final-refund');
    previewBody.innerHTML = '<p style="margin:0; color:#777; text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i> 서버 환불 스냅샷 계산 중...</p>';

    const itemsToRefund = [];
    if (scope === 'FULL') {
        (currentModalOrderData.items || []).forEach(it => {
            const remQty = Math.max(0, it.quantity - (it.shipped_qty || 0) - (it.cancelled_qty || 0));
            if (remQty > 0) itemsToRefund.push({ order_item_id: it.id, quantity: remQty });
        });
    } else {
        document.querySelectorAll('.modal-refund-item-qty').forEach(inp => {
            const itemId = parseInt(inp.dataset.itemId);
            const qty = parseInt(inp.value) || 0;
            if (qty > 0) itemsToRefund.push({ order_item_id: itemId, quantity: qty });
        });
    }

    if (itemsToRefund.length === 0) {
        previewBody.innerHTML = '<p style="color:#d32f2f; margin:0; text-align:center;">환불 가능한 수량이 선택되지 않았습니다.</p>';
        if (btnExecute) btnExecute.disabled = true;
        return;
    }

    try {
        const resp = await fetch(`/api/admin/orders/${orderId}/refund/preview`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: itemsToRefund, scope })
        });
        const data = await resp.json();
        if (resp.ok && data.preview_token) {
            document.getElementById('refund-preview-token').value = data.preview_token;
            previewBody.innerHTML = `
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span>상품 금액 합계:</span>
                    <span><strong>${(data.item_refund_subtotal || 0).toLocaleString()}원</strong></span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px; color:#666;">
                    <span>할인 차감액:</span>
                    <span>-${(data.allocated_discount_amount || 0).toLocaleString()}원</span>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:6px; color:#666;">
                    <span>배송비 환불액:</span>
                    <span>+${(data.shipping_refund_amount || 0).toLocaleString()}원</span>
                </div>
                <div style="font-size:1.1rem; color:#b84a4a; border-top:1px dashed #ffcdd2; padding-top:6px; display:flex; justify-content:space-between; align-items:center;">
                    <strong>최종 PG 결제 취소 예정:</strong>
                    <strong style="font-size:1.25rem;">${(data.final_refund_amount || 0).toLocaleString()}원</strong>
                </div>
            `;
            previewBody.dataset.refundItemsJson = JSON.stringify(itemsToRefund);

            // 최종 승인 버튼 텍스트 스마트 업데이트
            if (btnExecute) {
                btnExecute.disabled = !data.can_execute;
                btnExecute.textContent = scope === 'FULL' ? '주문 취소 및 결제취소' : '선택 상품 취소 및 부분환불';
            }
        } else {
            previewBody.innerHTML = `<p style="color:#d32f2f; margin:0;">${data.error || '환불 계산 실패'}</p>`;
            if (btnExecute) btnExecute.disabled = true;
        }
    } catch (err) {
        console.error(err);
        previewBody.innerHTML = '<p style="color:#d32f2f; margin:0;">오류가 발생했습니다.</p>';
        if (btnExecute) btnExecute.disabled = true;
    }
}

async function executeFinalAdminRefund(btnEl) {
    const orderId = document.getElementById('refund-target-order-id').value;
    const previewToken = document.getElementById('refund-preview-token').value;
    const scope = document.querySelector('input[name="refund_scope"]:checked')?.value || 'FULL';
    const previewBody = document.getElementById('refund-preview-body');
    const itemsJson = previewBody.dataset.refundItemsJson;
    const reasonCode = document.getElementById('refund-reason-code').value;
    const reasonCustom = document.getElementById('refund-reason-custom').value.trim();

    if (!itemsJson) { customAlert('환불 상품 정보가 올바르지 않습니다.', 'error'); return; }
    const reason = reasonCustom ? `[${reasonCode}] ${reasonCustom}` : reasonCode;

    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/refund/execute`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                items: JSON.parse(itemsJson),
                reason,
                preview_token: previewToken,
                scope
            })
        });
        const data = await resp.json();
        if (resp.ok) {
            customAlert(data.message || '환불이 성공적으로 처리되었습니다.', 'success');
            closeModal('adminRefundConfirmModal');
            closeModal('orderDetailModal');
            loadOrderSubTabCounts();
            loadOrders();
            loadDashboardMetrics();
        } else if (resp.status === 409 && data.code === 'REFUND_PREVIEW_STALE') {
            customAlert('주문 또는 결제 상태가 변경되었습니다. 환불 금액을 다시 확인해 주세요.', 'warning');
            triggerDebouncedPreview();
        } else {
            customAlert(data.error || '환불 처리 실패', 'error');
        }
    } catch (err) {
        console.error(err);
        customAlert('환불 요청 중 오류가 발생했습니다.', 'error');
    } finally {
        btnEl.disabled = false;
    }
}

async function executeReconcileRefund(orderId, btnEl) {
    const confirmed = await customConfirm('PG 취소 내역을 재대조하여 DB 상태를 복구하시겠습니까?', '재대조 복구 확인');
    if (!confirmed) return;
    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/orders/${orderId}/refund/reconcile`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' }
        });
        const data = await resp.json();
        if (resp.ok) {
            customAlert(data.message || '재대조 복구 완료', 'success');
            openOrderDetail(orderId);
            loadOrders();
            loadOrderSubTabCounts();
        } else {
            customAlert(data.error || '재대조 실패', 'error');
        }
    } catch (err) {
        console.error(err);
        customAlert('재대조 요청 실패', 'error');
    } finally {
        btnEl.disabled = false;
    }
}

// ── 운송장 CSV 기능 ────────────────────────────────────────────────────────────

async function exportOrdersCSV(type) {
    try {
        let url, filename;
        if (type === 'shipping') {
            // 송장 등록 양식 다운로드 → tracking-template API
            url = '/api/admin/orders/tracking-template';
            filename = `tracking_template_${new Date().toISOString().slice(0, 10)}.csv`;
        } else {
            // 관리자 전체 주문 CSV
            url = '/api/admin/orders/export?type=excel';
            filename = `order_export_${new Date().toISOString().slice(0, 10)}.csv`;
        }

        const resp = await fetch(url, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            customAlert(err.error || 'CSV 다운로드에 실패했습니다.', 'error');
            return;
        }

        const blob = await resp.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
    } catch (err) {
        console.error('CSV 다운로드 오류:', err);
        customAlert('CSV 다운로드 중 오류가 발생했습니다.', 'error');
    }
}

function importTrackingCSV() {
    const input = document.getElementById('tracking-csv-file-input');
    if (input) {
        input.value = '';  // 동일 파일 재선택 허용
        input.click();
    }
}

async function handleTrackingCSVFile(file) {
    if (!file) return;

    // 클라이언트 사전 검사
    if (!file.name.toLowerCase().endsWith('.csv')) {
        customAlert('.csv 파일만 업로드 가능합니다.', 'error');
        return;
    }
    if (file.size > 5 * 1024 * 1024) {
        customAlert('파일 크기는 5MB를 초과할 수 없습니다.', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        customAlert('송장 CSV를 처리 중입니다...', 'info');

        const resp = await fetch('/api/admin/orders/import-tracking-csv', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}` },
            body: formData
        });

        const data = await resp.json();

        if (!resp.ok) {
            customAlert(data.error || 'CSV 업로드에 실패했습니다.', 'error');
            return;
        }

        // 결과 리포트 팝업 렌더링 (XSS 방어: textContent만 사용)
        _renderTrackingImportResult(data);

        // 성공 건이 있으면 목록 갱신
        if (data.success > 0) {
            await loadOrders();
            await loadOrderSubTabCounts();
        }
    } catch (err) {
        console.error('송장 CSV 업로드 오류:', err);
        customAlert('업로드 중 서버 오류가 발생했습니다.', 'error');
    }
}

function _renderTrackingImportResult(data) {
    // 모달 컨테이너 생성 (기존 있으면 제거 후 재생성)
    const existing = document.getElementById('tracking-import-result-modal');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'tracking-import-result-modal';
    overlay.style.cssText = `
        position:fixed; inset:0; background:rgba(0,0,0,0.55);
        display:flex; align-items:center; justify-content:center; z-index:9999;
    `;

    const box = document.createElement('div');
    box.style.cssText = `
        background:#fff; border-radius:12px; padding:28px 32px;
        min-width:480px; max-width:680px; max-height:80vh;
        overflow-y:auto; box-shadow:0 8px 40px rgba(0,0,0,0.25);
        font-family:'Noto Sans KR', sans-serif;
    `;

    // 제목
    const title = document.createElement('h3');
    title.textContent = '송장 등록 결과';
    title.style.cssText = 'margin:0 0 16px 0; font-size:1.1rem; color:#1a1a2e; font-family:"Noto Serif KR",serif;';
    box.appendChild(title);

    // 요약 테이블
    const summary = document.createElement('div');
    summary.style.cssText = 'display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:20px;';
    [
        ['전체', data.total, '#455a64'],
        ['성공 ✅', data.success, '#2e7d32'],
        ['실패 ❌', data.failed, '#c62828'],
        ['건너뜀 ⏭', data.skipped, '#f57c00'],
    ].forEach(([label, count, color]) => {
        const cell = document.createElement('div');
        cell.style.cssText = `background:#f5f5f5; border-radius:8px; padding:10px 14px;
            display:flex; justify-content:space-between; align-items:center;`;
        const lbl = document.createElement('span');
        lbl.textContent = label;
        lbl.style.cssText = 'font-size:0.85rem; color:#555;';
        const val = document.createElement('strong');
        val.textContent = `${count}건`;
        val.style.color = color;
        cell.appendChild(lbl);
        cell.appendChild(val);
        summary.appendChild(cell);
    });
    box.appendChild(summary);

    // 실패 목록
    const failedRows = (data.results || []).filter(r => r.success === false);
    if (failedRows.length > 0) {
        const failTitle = document.createElement('h4');
        failTitle.textContent = '실패 내역';
        failTitle.style.cssText = 'margin:0 0 8px 0; font-size:0.9rem; color:#c62828;';
        box.appendChild(failTitle);

        const failList = document.createElement('div');
        failList.style.cssText = 'border:1px solid #ffcdd2; border-radius:8px; overflow:hidden; margin-bottom:16px;';
        failedRows.forEach((r, i) => {
            const item = document.createElement('div');
            item.style.cssText = `padding:8px 12px; background:${i % 2 === 0 ? '#fff8f8' : '#fff'};
                border-bottom:1px solid #ffcdd2; font-size:0.82rem;`;

            const top = document.createElement('div');
            top.style.cssText = 'display:flex; gap:8px; align-items:center; margin-bottom:2px;';

            const orderNum = document.createElement('strong');
            orderNum.textContent = r.order_number || '-';
            orderNum.style.color = '#c62828';

            const reason = document.createElement('span');
            reason.textContent = r.reason || '';
            reason.style.cssText = 'background:#ffebee; color:#b71c1c; padding:1px 6px; border-radius:4px; font-size:0.75rem;';

            top.appendChild(orderNum);
            top.appendChild(reason);

            const msg = document.createElement('div');
            msg.textContent = r.message || '';
            msg.style.color = '#666';

            item.appendChild(top);
            item.appendChild(msg);
            failList.appendChild(item);
        });
        box.appendChild(failList);
    }

    // 건너뜀 목록
    const skippedRows = (data.results || []).filter(r => r.skipped === true);
    if (skippedRows.length > 0) {
        const skipTitle = document.createElement('h4');
        skipTitle.textContent = '건너뜀';
        skipTitle.style.cssText = 'margin:0 0 8px 0; font-size:0.9rem; color:#f57c00;';
        box.appendChild(skipTitle);

        const skipList = document.createElement('div');
        skipList.style.cssText = 'border:1px solid #ffe0b2; border-radius:8px; overflow:hidden; margin-bottom:16px;';
        skippedRows.forEach((r, i) => {
            const item = document.createElement('div');
            item.style.cssText = `padding:8px 12px; background:${i % 2 === 0 ? '#fffde7' : '#fff'};
                border-bottom:1px solid #ffe0b2; font-size:0.82rem;`;

            const orderNum = document.createElement('strong');
            orderNum.textContent = r.order_number || '-';
            orderNum.style.color = '#f57c00';
            item.appendChild(orderNum);

            const sep = document.createElement('span');
            sep.textContent = '  ';
            item.appendChild(sep);

            const msg = document.createElement('span');
            msg.textContent = r.message || '';
            msg.style.color = '#666';
            item.appendChild(msg);

            skipList.appendChild(item);
        });
        box.appendChild(skipList);
    }

    // 확인 버튼
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '확인';
    closeBtn.style.cssText = `
        display:block; width:100%; padding:10px; margin-top:4px;
        background:var(--admin-primary,#6d4c41); color:#fff; border:none;
        border-radius:8px; font-size:0.95rem; font-weight:600; cursor:pointer;
    `;
    closeBtn.onclick = () => overlay.remove();
    box.appendChild(closeBtn);

    overlay.appendChild(box);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}
