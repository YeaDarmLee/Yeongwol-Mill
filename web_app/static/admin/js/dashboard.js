/* dashboard.js: 경영 대시보드 지표, 7일/30일 추이 차트, Work Queue & Alerts 모듈 (인터랙티브 애니메이션 적용) */

let dashboardTrendData = [];
let currentTrendPeriod = 7;
let chartAnimFrame = null;
let currentAnimProgress = 1.0;

/**
 * 숫자를 0부터 targetVal까지 부드럽게 카운트업 롤링하는 애니메이션 유틸
 */
function animateCountUp(elementId, targetVal, prefix = '', suffix = '', duration = 650) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const num = parseInt(targetVal) || 0;
    if (num === 0) {
        el.innerText = `${prefix}0${suffix}`;
        return;
    }

    const startTime = performance.now();

    function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // easeOutCubic
        const ease = 1 - Math.pow(1 - progress, 3);
        const currentVal = Math.round(num * ease);

        el.innerText = `${prefix}${currentVal.toLocaleString()}${suffix}`;

        if (progress < 1) {
            requestAnimationFrame(update);
        } else {
            el.innerText = `${prefix}${num.toLocaleString()}${suffix}`;
            el.classList.remove('count-updated');
            void el.offsetWidth; // trigger reflow
            el.classList.add('count-updated');
        }
    }

    requestAnimationFrame(update);
}

async function loadDashboardMetrics(isSilent = false) {
    try {
        const resp = await fetch('/api/admin/dashboard', {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();

        // 갱신 시각
        if (data.as_of) {
            document.getElementById('dash-as-of').innerText = data.as_of;
        }

        // A. KPI 카드 카운트업 애니메이션
        if (data.kpi) {
            animateCountUp('val-kpi-today-orders', data.kpi.today_orders, '', '건');
            animateCountUp('val-kpi-today-net', data.kpi.today_net_sales, '', '원');
            animateCountUp('val-kpi-gross-sub', data.kpi.today_gross_sales, '', '원');
            animateCountUp('val-kpi-refund-sub', data.kpi.today_refunds, '-', '원');
            animateCountUp('val-kpi-preparing', data.kpi.pending_shipping_count, '', '건');
            animateCountUp('val-kpi-reconciling', data.kpi.reconciling_total, '', '건');
            animateCountUp('val-kpi-lowstock', data.kpi.low_stock_count, '', '개');

            if (data.kpi.reconciling_breakdown) {
                const b = data.kpi.reconciling_breakdown;
                const subStr = `처리 ${b.PROCESSING || 0} / 대조 ${b.RECONCILING || 0}`;
                document.getElementById('val-kpi-reconcile-sub').innerText = subStr;
            }
        }

        // B. Action Work Queue (정상 주문 5개 / 클레임·관리 5개)
        if (data.work_queue) {
            const q = data.work_queue;
            // 윗줄: 정상 프로세스
            setQueueCardValue('q-val-pending', 'qc-pending', q.pending_orders);
            setQueueCardValue('q-val-confirmed', 'qc-confirmed', q.confirmed_orders);
            setQueueCardValue('q-val-preparing', 'qc-preparing', q.preparing_orders);
            setQueueCardValue('q-val-shipping', 'qc-shipping', q.shipping_orders);
            setQueueCardValue('q-val-delivered', 'qc-delivered', q.delivered_orders);

            // 아래줄: 클레임 / 이슈 관리 (24H 지연출고, 환불접수, 환불처리, 상태대조, 금액불일치)
            setQueueCardValue('q-val-stale-preparing', 'qc-stale-preparing', q.stale_unregistered, true);
            setQueueCardValue('q-val-refund-req', 'qc-refund-req', q.refund_pending);
            setQueueCardValue('q-val-refund-proc', 'qc-refund-proc', q.refund_processing);
            setQueueCardValue('q-val-reconciling', 'qc-reconciling', q.reconciling, true);
            setQueueCardValue('q-val-mismatch', 'qc-mismatch', q.amount_mismatch, true);
        }

        // C. Alerts (운영 알림)
        const alertsContainer = document.getElementById('dashboard-alerts-container');
        if (data.alerts && data.alerts.length > 0) {
            alertsContainer.innerHTML = data.alerts.map((a, idx) => `
                <div class="alert-card-item level-${a.level} stagger-row" style="animation-delay: ${idx * 60}ms;" onclick="handleAlertClick('${a.target_filter || ''}')">
                    <div>
                        <strong>${a.title}</strong>
                        <div style="font-size:0.85rem; opacity:0.9;">${a.message}</div>
                    </div>
                    <span style="font-size:0.75rem; background:rgba(0,0,0,0.06); padding:2px 8px; border-radius:4px;">상세조회 &gt;</span>
                </div>
            `).join('');
        } else {
            alertsContainer.innerHTML = `
                <div class="alert-empty-success">
                    현재 긴급 운영 이슈가 없습니다.
                </div>
            `;
        }

        // D. Recent Orders (최근 8건, 스태거 슬라이드업 애니메이션)
        const recentTbody = document.getElementById('dash-recent-orders-tbody');
        if (data.recent_orders && data.recent_orders.length > 0) {
            recentTbody.innerHTML = data.recent_orders.map((ord, idx) => `
                <tr class="stagger-row" style="animation-delay: ${idx * 40}ms;">
                    <td><strong>${ord.order_number}</strong></td>
                    <td style="font-size:0.82rem; color:#666;">${ord.created_at}</td>
                    <td>${ord.customer_name_masked}</td>
                    <td><strong>${ord.total_amount.toLocaleString()}원</strong></td>
                    <td><span class="status-badge status-${ord.order_status}">${getOrderStatusKo(ord.order_status)}</span></td>
                    <td><span class="status-badge status-${ord.payment_status}">${getPaymentStatusKo(ord.payment_status)}</span></td>
                    <td>
                        ${ord.has_tracking
                    ? `<span style="font-size:0.75rem; color:#2e7d32; font-weight:600;">등록완료 (${ord.courier_name || '택배'})</span>`
                    : `<span style="font-size:0.75rem; color:#d32f2f; font-weight:600;">미등록</span>`}
                    </td>
                    <td>
                        <button class="btn-action" style="padding:3px 8px; font-size:0.8rem;" onclick="openOrderDetail(${ord.id})">상세 관리</button>
                    </td>
                </tr>
            `).join('');
        } else {
            recentTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#777;">최근 주문 데이터가 없습니다.</td></tr>`;
        }

        // E. Stock Warnings (재고 경고 상품 스태거 애니메이션)
        const stockTbody = document.getElementById('dash-stock-tbody');
        if (data.low_stock_options && data.low_stock_options.length > 0) {
            stockTbody.innerHTML = data.low_stock_options.map((opt, idx) => {
                const available = opt.stock - opt.reserved_stock;
                const isCritical = available < 0;
                return `
                    <tr class="stagger-row" style="animation-delay: ${idx * 40}ms;">
                        <td><strong>${opt.product_name}</strong></td>
                        <td>${opt.option_name}</td>
                        <td>${opt.stock}개</td>
                        <td>${opt.reserved_stock}개</td>
                        <td style="font-weight:bold; color:${isCritical ? '#d32f2f' : '#ed6c02'};">
                            ${available}개 ${isCritical ? '⚠ (초과)' : ''}
                        </td>
                        <td>
                            <button class="btn-action" style="padding:2px 6px; font-size:0.75rem;" onclick="navigatePage('products')">재고 수정</button>
                        </td>
                    </tr>
                `;
            }).join('');
        } else {
            document.getElementById('dash-stock-wrapper').innerHTML = `
                <div class="alert-empty-success" style="margin-top:10px;">
                    모든 상품의 재고가 안전 수준입니다.
                </div>
            `;
        }

        // F. Trend Chart 30일 데이터 (부드러운 모션 드로우 렌더링)
        if (data.trend_30days) {
            dashboardTrendData = data.trend_30days;
            startChartAnimation(currentTrendPeriod);
        }

    } catch (err) {
        console.error('대시보드 메트릭 로드 오류:', err);
    }
}

function setQueueCardValue(valElemId, cardElemId, count, isUrgentAlert = false) {
    const cardEl = document.getElementById(cardElemId);
    if (cardEl) {
        cardEl.classList.remove('has-items', 'has-urgent');
        if (count > 0) {
            if (isUrgentAlert) cardEl.classList.add('has-urgent');
            else cardEl.classList.add('has-items');
        }
    }
    animateCountUp(valElemId, count, '', '');
}

function handleAlertClick(targetFilterStr) {
    if (!targetFilterStr) return;
    navigatePage('orders');
    const params = new URLSearchParams(targetFilterStr);
    loadOrders({
        order_status: params.get('order_status') || '',
        payment_status: params.get('payment_status') || '',
        refund_status: params.get('refund_status') || '',
        unregistered_tracking: params.get('unregistered_tracking') || '',
        amount_mismatch: params.get('amount_mismatch') || ''
    });
}

function switchTrendPeriod(days) {
    currentTrendPeriod = days;
    document.getElementById('btn-chart-7d').classList.toggle('active', days === 7);
    document.getElementById('btn-chart-30d').classList.toggle('active', days === 30);
    startChartAnimation(days);
}

function startChartAnimation(days) {
    if (chartAnimFrame) cancelAnimationFrame(chartAnimFrame);
    const startTime = performance.now();
    const duration = 650;

    function frame(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // easeOutCubic
        const ease = 1 - Math.pow(1 - progress, 3);
        currentAnimProgress = ease;
        renderTrendChart(days, currentHoveredIdx, ease);

        if (progress < 1) {
            chartAnimFrame = requestAnimationFrame(frame);
        }
    }

    chartAnimFrame = requestAnimationFrame(frame);
}

let isChartHoverSetup = false;
let currentHoveredIdx = -1;

function renderTrendChart(days, hoveredIdx = -1, animProgress = 1.0) {
    const canvas = document.getElementById('dashTrendCanvas');
    if (!canvas || !dashboardTrendData || dashboardTrendData.length === 0) return;

    // 마우스 호버 이벤트 최초 1회 등록
    if (!isChartHoverSetup) {
        setupChartHoverEvents(canvas);
        isChartHoverSetup = true;
    }

    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * (window.devicePixelRatio || 1);
    canvas.height = rect.height * (window.devicePixelRatio || 1);
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

    const dataSlice = dashboardTrendData.slice(-days);
    const width = rect.width;
    const height = rect.height;
    const padding = { top: 20, right: 30, bottom: 30, left: 45 };

    ctx.clearRect(0, 0, width, height);

    const maxSales = Math.max(...dataSlice.map(d => d.net_payments), 100000);
    const maxOrders = Math.max(...dataSlice.map(d => d.paid_orders), 5);

    const graphW = width - padding.left - padding.right;
    const graphH = height - padding.top - padding.bottom;
    const stepX = graphW / Math.max(dataSlice.length - 1, 1);

    // 가이드 라인
    ctx.strokeStyle = '#eee';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
        const y = padding.top + (graphH / 3) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(width - padding.right, y);
        ctx.stroke();

        const valLabel = Math.round((maxSales * (3 - i)) / 3 / 1000) + 'k';
        ctx.fillStyle = '#888';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(valLabel, padding.left - 6, y + 3);
    }

    // 마우스 호버 수직 가이드라인
    if (hoveredIdx >= 0 && hoveredIdx < dataSlice.length) {
        const hx = padding.left + hoveredIdx * stepX;
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = 'rgba(197, 155, 39, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(hx, padding.top);
        ctx.lineTo(hx, height - padding.bottom);
        ctx.stroke();
        ctx.restore();
    }

    // 순매출 막대 그래프 (animProgress 반영)
    const barWidth = Math.max(stepX * 0.4, 4);
    dataSlice.forEach((d, idx) => {
        const x = padding.left + idx * stepX;
        const fullBarH = (d.net_payments / maxSales) * graphH;
        const barH = fullBarH * animProgress;
        const y = padding.top + (graphH - barH);

        const isHovered = idx === hoveredIdx;
        ctx.fillStyle = isHovered ? 'rgba(197, 155, 39, 0.85)' : 'rgba(197, 155, 39, 0.45)';
        ctx.fillRect(x - barWidth / 2, y, barWidth, barH);
        ctx.strokeStyle = isHovered ? '#8c6b12' : '#c59b27';
        ctx.lineWidth = isHovered ? 2 : 1;
        ctx.strokeRect(x - barWidth / 2, y, barWidth, barH);

        // X축 라벨
        if (days === 7 || idx % Math.ceil(days / 10) === 0 || isHovered) {
            ctx.fillStyle = isHovered ? '#c59b27' : '#666';
            ctx.font = isHovered ? 'bold 11px sans-serif' : '10px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(d.date.substring(5), x, height - 10);
        }
    });

    // 주문건수 꺾은선 그래프 (animProgress 반영)
    if (animProgress > 0.05) {
        const visibleCount = Math.max(1, Math.floor(dataSlice.length * animProgress));
        ctx.beginPath();
        ctx.strokeStyle = '#2e7d32';
        ctx.lineWidth = 2;
        dataSlice.slice(0, visibleCount).forEach((d, idx) => {
            const x = padding.left + idx * stepX;
            const fullPointH = (d.paid_orders / maxOrders) * graphH;
            const pointH = fullPointH * animProgress;
            const y = padding.top + (graphH - pointH);
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 포인트 정점
        dataSlice.slice(0, visibleCount).forEach((d, idx) => {
            const x = padding.left + idx * stepX;
            const fullPointH = (d.paid_orders / maxOrders) * graphH;
            const pointH = fullPointH * animProgress;
            const y = padding.top + (graphH - pointH);
            const isHovered = idx === hoveredIdx;

            ctx.beginPath();
            ctx.arc(x, y, isHovered ? 6 : 3, 0, Math.PI * 2);
            ctx.fillStyle = isHovered ? '#1b5e20' : '#2e7d32';
            ctx.fill();

            if (isHovered) {
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 2;
                ctx.stroke();
            }
        });
    }
}

function setupChartHoverEvents(canvas) {
    const container = canvas.parentElement;
    let tooltipEl = document.getElementById('dashTrendTooltip');
    if (!tooltipEl) {
        tooltipEl = document.createElement('div');
        tooltipEl.id = 'dashTrendTooltip';
        tooltipEl.style.cssText = `
            position: absolute;
            display: none;
            pointer-events: none;
            background: rgba(30, 21, 18, 0.92);
            color: #ffffff;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 0.8rem;
            box-shadow: 0 4px 16px rgba(0,0,0,0.25);
            z-index: 100;
            border: 1px solid rgba(197, 155, 39, 0.4);
            backdrop-filter: blur(4px);
            white-space: nowrap;
            transition: left 0.05s ease-out, top 0.05s ease-out;
        `;
        container.appendChild(tooltipEl);
    }

    canvas.addEventListener('mousemove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const dataSlice = dashboardTrendData.slice(-currentTrendPeriod);
        if (!dataSlice || dataSlice.length === 0) return;

        const padding = { top: 20, right: 30, bottom: 30, left: 45 };
        const graphW = rect.width - padding.left - padding.right;
        const stepX = graphW / Math.max(dataSlice.length - 1, 1);

        // 가장 가까운 포인트 찾기
        let closestIdx = -1;
        let minDiff = Infinity;

        dataSlice.forEach((d, idx) => {
            const px = padding.left + idx * stepX;
            const diff = Math.abs(mouseX - px);
            if (diff < minDiff) {
                minDiff = diff;
                closestIdx = idx;
            }
        });

        // 영역 밖이면 숨기기
        if (mouseX < padding.left - 10 || mouseX > rect.width - padding.right + 10 || closestIdx < 0) {
            if (currentHoveredIdx !== -1) {
                currentHoveredIdx = -1;
                renderTrendChart(currentTrendPeriod, -1, currentAnimProgress);
                tooltipEl.style.display = 'none';
            }
            return;
        }

        if (currentHoveredIdx !== closestIdx) {
            currentHoveredIdx = closestIdx;
            renderTrendChart(currentTrendPeriod, closestIdx, currentAnimProgress);
        }

        const d = dataSlice[closestIdx];
        tooltipEl.innerHTML = `
            <div style="font-weight:700; color:#f1e4d3; margin-bottom:4px; border-bottom:1px solid rgba(255,255,255,0.15); padding-bottom:3px;">
                ${d.date}
            </div>
            <div style="display:flex; justify-content:space-between; gap:12px; margin-top:2px;">
                <span style="color:#e0d0b0;">순매출:</span>
                <strong style="color:#c59b27;">${(d.net_payments || 0).toLocaleString()}원</strong>
            </div>
            <div style="display:flex; justify-content:space-between; gap:12px; margin-top:2px;">
                <span style="color:#e0d0b0;">결제건수:</span>
                <strong style="color:#81c784;">${(d.paid_orders || 0).toLocaleString()}건</strong>
            </div>
        `;
        tooltipEl.style.display = 'block';

        // 툴팁 위치 조절 (캔버스 좌우 가장자리 무넘침 방지)
        const tooltipW = tooltipEl.offsetWidth;
        const targetX = padding.left + closestIdx * stepX;
        let posX = targetX + 15;
        if (posX + tooltipW > rect.width - 10) {
            posX = targetX - tooltipW - 15;
        }

        tooltipEl.style.left = `${posX}px`;
        tooltipEl.style.top = `${Math.max(10, mouseY - 30)}px`;
    });

    canvas.addEventListener('mouseleave', () => {
        currentHoveredIdx = -1;
        renderTrendChart(currentTrendPeriod, -1, currentAnimProgress);
        if (tooltipEl) tooltipEl.style.display = 'none';
    });
}

/**
 * 대시보드 KPI 카드 또는 Work Queue 에서 주문 페이지로 이동하며 필터를 적용하는 유틸
 * @param {string} orderStatus     - order_status 필터값 ('' = 전체)
 * @param {string} paymentStatus   - payment_status 필터값
 * @param {string} refundStatus    - refund_status 필터값
 * @param {string} unregisteredTracking - 'true' 이면 송장 미등록관
 * @param {string} amountMismatch - 'true' 이면 금액 불일치
 */
function navigateToOrdersWithFilter(orderStatus = '', paymentStatus = '', refundStatus = '', unregisteredTracking = '', amountMismatch = '') {
    navigatePage('orders');
    loadOrders({
        order_status: orderStatus,
        payment_status: paymentStatus,
        refund_status: refundStatus,
        unregistered_tracking: unregisteredTracking,
        amount_mismatch: amountMismatch
    });
}
