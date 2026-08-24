/* orders.js: 주문 관리, 필터링, 주문 상세 모달, 운송장 처리, 2단계 환불 모듈 */

let currentModalOrderData = null;
let ordersCurrentPage = 1;
const ORDERS_PAGE_LIMIT = 10;

async function loadOrders(customFilters = null, page = null) {
    if (page !== null) ordersCurrentPage = page;

    try {
        const params = new URLSearchParams();
        params.set('page', ordersCurrentPage);
        params.set('limit', ORDERS_PAGE_LIMIT);

        // 필터 UI 값 읽기 or 외부 필터 적용
        const os = customFilters?.order_status ?? (document.getElementById('order-status-filter')?.value || '');
        const ps = customFilters?.payment_status ?? (document.getElementById('payment-status-filter')?.value || '');
        const rs = customFilters?.refund_status ?? (document.getElementById('refund-status-filter')?.value || '');
        const ut = customFilters?.unregistered_tracking ?? (document.getElementById('unregistered-tracking-filter')?.value || '');
        const am = customFilters?.amount_mismatch ?? (document.getElementById('amount-mismatch-filter')?.value || '');
        const kw = customFilters?.keyword ?? (document.getElementById('order-keyword-filter')?.value || '');

        if (customFilters) {
            if (document.getElementById('order-status-filter')) document.getElementById('order-status-filter').value = os;
            if (document.getElementById('payment-status-filter')) document.getElementById('payment-status-filter').value = ps;
            if (document.getElementById('refund-status-filter')) document.getElementById('refund-status-filter').value = rs;
            if (document.getElementById('unregistered-tracking-filter')) document.getElementById('unregistered-tracking-filter').value = ut;
            if (document.getElementById('amount-mismatch-filter')) document.getElementById('amount-mismatch-filter').value = am;
            if (document.getElementById('order-keyword-filter')) document.getElementById('order-keyword-filter').value = kw;
            ordersCurrentPage = 1;
            params.set('page', 1);
        }

        if (os) params.set('order_status', os);
        if (ps) params.set('payment_status', ps);
        if (rs) params.set('refund_status', rs);
        if (ut) params.set('unregistered_tracking', ut);
        if (am) params.set('amount_mismatch', am);
        if (kw) params.set('keyword', kw);

        const resp = await fetch(`/api/admin/orders?${params.toString()}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const tbody = document.getElementById('orders-tbody');
        if (!tbody) return;

        if (!data.orders || data.orders.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:#777; padding:1.5rem;">조건에 맞는 주문 내역이 없습니다.</td></tr>`;
        } else {
            tbody.innerHTML = data.orders.map(ord => `
                <tr>
                    <td>${ord.id}</td>
                    <td><strong>${ord.order_number}</strong></td>
                    <td>${ord.recipient_name || ord.guest_name || '구매자'}</td>
                    <td>${ord.recipient_phone || '-'}</td>
                    <td><strong>${(ord.total_amount || 0).toLocaleString()}원</strong></td>
                    <td><span class="status-badge status-${ord.order_status}">${getOrderStatusKo(ord.order_status)}</span></td>
                    <td><span class="status-badge status-${ord.payment_status}">${getPaymentStatusKo(ord.payment_status)}</span></td>
                    <td>
                        ${ord.tracking_number
                ? `<span style="font-size:0.75rem; color:#2e7d32; font-weight:600;">${ord.courier_name || ''} ${ord.tracking_number}</span>`
                : `<span style="font-size:0.75rem; color:#d32f2f; font-weight:600;">미등록</span>`}
                    </td>
                    <td>
                        <button class="btn-action" style="padding:4px 8px; font-size:0.8rem;" onclick="openOrderDetail(${ord.id})">상세 관리</button>
                    </td>
                </tr>
            `).join('');
        }

        // 페이지네이션 렌더링
        renderPaginationBar('orders-pagination', data.pagination, 'ordersGoPage');

    } catch (err) { console.error('주문 데이터 로드 예외:', err); }
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
    ['order-status-filter','payment-status-filter','refund-status-filter',
     'unregistered-tracking-filter','amount-mismatch-filter','order-keyword-filter']
        .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    ordersCurrentPage = 1;
    loadOrders();
}

async function openOrderDetail(orderId) {
    try {
        const resp = await fetch(`/api/admin/orders/${orderId}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) {
            customAlert('주문 상세 정보를 불러오지 못했습니다.', 'error');
            return;
        }
        const data = await resp.json();
        currentModalOrderData = data;
        const ord = data.order;
        const items = data.items || [];
        const notes = data.admin_notes || [];
        const timeline = data.timeline || [];

        const isShipped = ['SHIPPING', 'DELIVERED', 'CANCELLED'].includes(ord.order_status);
        const adminUser = JSON.parse(localStorage.getItem('yw_admin_user') || '{}');
        const isSuperAdmin = (adminUser.role === 'SUPER_ADMIN');

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
                        <div><strong>${(it.subtotal).toLocaleString()}원</strong></div>
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
                        ${['PENDING','CONFIRMED','PREPARING','SHIPPING','DELIVERED'].map(s =>
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
                        ${['CJ대한통운','우체국택배','한진택배','롯데택배','로젠택배'].map(c =>
                            `<option value="${c}" ${ord.courier_name === c ? 'selected' : ''}>${c}</option>`
                        ).join('')}
                    </select>
                    <input type="text" id="modal-tracking-input" class="form-control" placeholder="운송장 번호 입력" value="${ord.tracking_number || ''}" style="flex:1; padding:6px 10px; font-size:0.85rem;" ${isShipped ? 'disabled' : ''}>
                    <button type="button" onclick="submitRegisterTracking(${ord.id}, this)" class="btn-action" style="background:${isShipped ? '#9e9e9e' : 'var(--admin-primary)'}; color:#fff; padding:6px 14px; font-size:0.85rem; font-weight:600;" ${isShipped ? 'disabled' : ''}>
                        운송장 등록 및 출고
                    </button>
                </div>
                ${isShipped ? `<div style="font-size:0.8rem; color:#d32f2f; font-weight:600; margin-top:6px;">배송중 이상 상태에서는 운송장 변경이 차단됩니다.</div>` : ''}
                ${ord.shipped_at ? `<div style="font-size:0.8rem; color:#666; margin-top:4px;">최초 출고시각: ${ord.shipped_at}</div>` : ''}
            </div>

            <div style="background:#fff; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin-bottom:1.2rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <h4 style="font-size:0.95rem; font-family:'Noto Serif KR', serif; margin:0; color:#2c3e50;">상품 및 환불 관리</h4>
                    <span style="font-size:0.75rem; color:#2e7d32; font-weight:600;">관리자 환불 처리 권한 보유</span>
                </div>
                ${itemsHtml}
                <div style="text-align:right; font-size:1.1rem; color:#915a28; margin:10px 0;"><strong>총 결제금액: ${ord.total_amount.toLocaleString()}원</strong></div>
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
        if (resp.ok) { customAlert(data.message || '상태 변경 완료', 'success'); openOrderDetail(orderId); loadOrders(); }
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
        if (resp.ok) { customAlert(data.message || '운송장 등록 완료', 'success'); openOrderDetail(orderId); loadOrders(); }
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
            loadOrders();
            loadDashboardMetrics();
        } else customAlert(data.error || '환불 처리 실패', 'error');
    } catch (err) { console.error(err); customAlert('환불 요청 중 오류 발생', 'error'); }
    finally { btnEl.disabled = false; }
}
