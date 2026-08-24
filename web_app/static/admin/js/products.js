/* products.js: 상품 및 옵션/가용재고 관리 모듈 (무제한 재고 설정, 검색, 필터, 페이지네이션 포함) */

let productsCurrentPage = 1;
const PRODUCTS_PAGE_LIMIT = 10;

async function loadProducts(page = null) {
    if (page !== null) productsCurrentPage = page;

    try {
        const params = new URLSearchParams();
        params.set('page', productsCurrentPage);
        params.set('limit', PRODUCTS_PAGE_LIMIT);

        const keyword = document.getElementById('product-keyword-filter')?.value.trim() || '';
        const categoryId = document.getElementById('product-category-filter')?.value || '';
        const isActive = document.getElementById('product-active-filter')?.value || '';

        if (keyword) params.set('keyword', keyword);
        if (categoryId) params.set('category_id', categoryId);
        if (isActive !== '') params.set('is_active', isActive);

        const resp = await fetch(`/api/admin/products?${params.toString()}`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const tbody = document.getElementById('products-tbody');
        if (!tbody) return;

        if (!data.products || data.products.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#777; padding:1.5rem;">조건에 맞는 상품이 없습니다.</td></tr>`;
        } else {
            tbody.innerHTML = data.products.map(p => {
                const optionsStr = (p.options || []).map(o => {
                    const isUnlimited = o.stock >= 999000;
                    const avail = isUnlimited ? '∞ (무제한)' : (o.stock - o.reserved_stock);
                    const stockDisplay = isUnlimited ? '∞ (무제한)' : `${o.stock}개`;
                    const availDisplay = isUnlimited ? '∞ (무제한)' : `${avail}개`;
                    const colorStyle = isUnlimited ? '#2e7d32' : ((o.stock - o.reserved_stock) < 5 ? '#d32f2f' : '#2e7d32');
                    return `<span style="font-size:0.78rem;">${o.option_name}: 보유 ${stockDisplay} / 가용 <strong style="color:${colorStyle}">${availDisplay}</strong></span>`;
                }).join('<br>');
                return `
                    <tr>
                        <td>${p.id}</td>
                        <td>
                            <strong>${p.name}</strong>
                            <span style="font-size:0.75rem; color:#888; margin-left:4px;">(${p.capacity || ''})</span>
                            ${p.category_name ? `<br><span style="font-size:0.75rem; color:#aaa;">${p.category_name}</span>` : ''}
                        </td>
                        <td>${(p.price || 0).toLocaleString()}원</td>
                        <td style="font-size:0.82rem; color:#555;">${optionsStr || '<span style="color:#aaa;">옵션 없음</span>'}</td>
                        <td>
                            <span class="status-badge ${p.is_active ? 'status-PREPARING' : 'status-CANCELLED'}">
                                ${p.is_active ? '판매중' : '판매중지'}
                            </span>
                        </td>
                        <td>
                            <button class="btn-action" style="padding:4px 8px; font-size:0.8rem;" onclick="openEditProductModal(${p.id})">수정/재고</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        renderPaginationBar('products-pagination', data.pagination, 'productsGoPage');

    } catch (err) { console.error('상품 데이터 로드 예외:', err); }
}

function productsGoPage(page) {
    productsCurrentPage = page;
    loadProducts(page);
}

function filterProducts() {
    productsCurrentPage = 1;
    loadProducts();
}

function resetProductFilters() {
    ['product-keyword-filter','product-category-filter','product-active-filter']
        .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    productsCurrentPage = 1;
    loadProducts();
}

/**
 * 무제한 재고 체크박스 토글 함수
 */
function toggleOptionUnlimited(chkEl) {
    const row = chkEl.closest('div');
    const stockInput = row.querySelector('.create-opt-stock, .edit-opt-stock');
    if (!stockInput) return;

    if (chkEl.checked) {
        stockInput.dataset.prevStock = stockInput.value;
        stockInput.value = 999999;
        stockInput.disabled = true;
    } else {
        stockInput.disabled = false;
        stockInput.value = stockInput.dataset.prevStock && stockInput.dataset.prevStock < 999000 ? stockInput.dataset.prevStock : 50;
    }
}

function openAddProductModal() {
    const container = document.getElementById('create-prod-options-container');
    if (container) {
        container.innerHTML = '';
        addCreateOptionRow({ option_name: '300ml (기본)', additional_price: 0, stock: 100 });
    }
    openModal('createProductModal');
}

function addCreateOptionRow(optData = null) {
    const container = document.getElementById('create-prod-options-container');
    if (!container) return;
    const isUnlimited = optData && optData.stock >= 999000;
    const stockVal = isUnlimited ? 999999 : (optData ? optData.stock : 50);

    const div = document.createElement('div');
    div.className = 'create-opt-row';
    div.style.cssText = 'display:flex; gap:8px; align-items:center; background:#fff; padding:8px; border-radius:6px; border:1px solid #ddd;';
    div.innerHTML = `
        <input type="text" class="form-control create-opt-name" placeholder="옵션명 (예: 300ml)" value="${optData ? optData.option_name : ''}" style="flex:2; padding:4px 8px;" required>
        <input type="number" class="form-control create-opt-price" placeholder="추가금액" value="${optData ? optData.additional_price : 0}" style="flex:1; padding:4px 8px;" required>
        <input type="number" class="form-control create-opt-stock" placeholder="재고수량" value="${stockVal}" ${isUnlimited ? 'disabled' : ''} style="flex:1; padding:4px 8px;" required>
        <label style="font-size:0.8rem; color:#555; display:flex; align-items:center; gap:3px; cursor:pointer; white-space:nowrap;">
            <input type="checkbox" class="opt-unlimited-chk" ${isUnlimited ? 'checked' : ''} onchange="toggleOptionUnlimited(this)"> 무제한
        </label>
        <button type="button" class="btn-action" style="background:#d32f2f; color:#fff; padding:4px 8px;" onclick="this.parentElement.remove()">삭제</button>
    `;
    container.appendChild(div);
}

async function submitAddProduct(btnEl) {
    const name = document.getElementById('create-prod-name').value.trim();
    const category_id = parseInt(document.getElementById('create-prod-category').value);
    const price = parseInt(document.getElementById('create-prod-price').value);
    const capacity = document.getElementById('create-prod-capacity').value.trim();
    const food_type = document.getElementById('create-prod-foodtype').value.trim();
    const manufacturer = document.getElementById('create-prod-manufacturer').value.trim();
    const shelf_life_text = document.getElementById('create-prod-shelflife').value.trim();
    const contents_capacity = document.getElementById('create-prod-contentscap').value.trim();
    const origin_info = document.getElementById('create-prod-origin').value.trim();
    const cs_phone = document.getElementById('create-prod-csphone').value.trim();
    const storage_method = document.getElementById('create-prod-storage').value.trim();
    const allergy_notice = document.getElementById('create-prod-allergy').value.trim();

    if (!name || isNaN(price)) { customAlert('상품명과 기본 판매가를 정확히 입력해 주세요.', 'error'); return; }

    const options = [];
    document.querySelectorAll('.create-opt-row').forEach(row => {
        const optName = row.querySelector('.create-opt-name').value.trim();
        const optPrice = parseInt(row.querySelector('.create-opt-price').value) || 0;
        const isUnlimited = row.querySelector('.opt-unlimited-chk')?.checked;
        const optStock = isUnlimited ? 999999 : (parseInt(row.querySelector('.create-opt-stock').value) || 0);
        if (optName) options.push({ option_name: optName, additional_price: optPrice, stock: optStock });
    });

    try {
        btnEl.disabled = true;
        const resp = await fetch('/api/admin/products', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, category_id, price, capacity, food_type, manufacturer, shelf_life_text, contents_capacity, origin_info, cs_phone, storage_method, allergy_notice, options })
        });
        const data = await resp.json();
        if (resp.ok) { customAlert(data.message || '상품 등록 완료', 'success'); closeModal('createProductModal'); loadProducts(); loadDashboardMetrics(); }
        else customAlert(data.error || '상품 등록 실패', 'error');
    } catch (err) { console.error(err); customAlert('상품 등록 요청 중 오류 발생', 'error'); }
    finally { btnEl.disabled = false; }
}

async function openEditProductModal(productId) {
    try {
        const resp = await fetch(`/api/admin/products?page=1&limit=1000`, {
            headers: { 'Authorization': `Bearer ${adminToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const p = (data.products || []).find(item => item.id === productId);
        if (!p) { customAlert('상품 정보를 찾을 수 없습니다.', 'error'); return; }

        document.getElementById('edit-prod-id').value = p.id;
        document.getElementById('edit-prod-name').value = p.name;
        document.getElementById('edit-prod-category').value = p.category_id;
        document.getElementById('edit-prod-price').value = p.price;
        document.getElementById('edit-prod-capacity').value = p.capacity || '';
        document.getElementById('edit-prod-description').value = p.description || '';
        document.getElementById('edit-prod-active').value = p.is_active ? 1 : 0;
        document.getElementById('edit-prod-foodtype').value = p.food_type || '식용유지류';
        document.getElementById('edit-prod-manufacturer').value = p.manufacturer || '영월고향방앗간';
        document.getElementById('edit-prod-shelflife').value = p.shelf_life_text || '제조일로부터 12개월';
        document.getElementById('edit-prod-contentscap').value = p.contents_capacity || p.capacity || '';
        document.getElementById('edit-prod-origin').value = p.origin_info || '참깨/들깨: 국산(강원도 영월군 100%)';
        document.getElementById('edit-prod-csphone').value = p.cs_phone || '033-000-0000';
        document.getElementById('edit-prod-storage').value = p.storage_method || '직사광선을 피하고 서늘한 곳 보관';
        document.getElementById('edit-prod-allergy').value = p.allergy_notice || '참깨/들깨 함유';

        const optionsContainer = document.getElementById('edit-prod-options-container');
        optionsContainer.innerHTML = '';
        if (p.options && p.options.length > 0) p.options.forEach(opt => addEditOptionRow(opt));
        else addEditOptionRow({ option_name: '300ml (기본)', additional_price: 0, stock: 100 });

        openModal('editProductModal');
    } catch (err) { console.error(err); }
}

function addEditOptionRow(optData = null) {
    const container = document.getElementById('edit-prod-options-container');
    if (!container) return;
    const isUnlimited = optData && optData.stock >= 999000;
    const stockVal = isUnlimited ? 999999 : (optData ? optData.stock : 50);

    const div = document.createElement('div');
    div.className = 'edit-opt-row';
    div.style.cssText = 'display:flex; gap:8px; align-items:center; background:#faf8f5; padding:8px; border-radius:6px; border:1px solid #ebe6df;';
    if (optData && optData.id) div.dataset.optId = optData.id;
    div.innerHTML = `
        <input type="text" class="form-control edit-opt-name" placeholder="옵션명" value="${optData ? optData.option_name : ''}" style="flex:2; padding:4px 8px;" required>
        <input type="number" class="form-control edit-opt-price" placeholder="추가금액" value="${optData ? optData.additional_price : 0}" style="flex:1; padding:4px 8px;" required>
        <input type="number" class="form-control edit-opt-stock" placeholder="재고수량" value="${stockVal}" ${isUnlimited ? 'disabled' : ''} style="flex:1; padding:4px 8px;" required>
        <label style="font-size:0.8rem; color:#555; display:flex; align-items:center; gap:3px; cursor:pointer; white-space:nowrap;">
            <input type="checkbox" class="opt-unlimited-chk" ${isUnlimited ? 'checked' : ''} onchange="toggleOptionUnlimited(this)"> 무제한
        </label>
        <button type="button" class="btn-action" style="background:#d32f2f; color:#fff; padding:4px 8px;" onclick="this.parentElement.remove()">삭제</button>
    `;
    container.appendChild(div);
}

async function submitEditProduct(btnEl) {
    const productId = document.getElementById('edit-prod-id').value;
    const name = document.getElementById('edit-prod-name').value.trim();
    const category_id = parseInt(document.getElementById('edit-prod-category').value);
    const price = parseInt(document.getElementById('edit-prod-price').value);
    const capacity = document.getElementById('edit-prod-capacity').value.trim();
    const description = document.getElementById('edit-prod-description').value.trim();
    const is_active = parseInt(document.getElementById('edit-prod-active').value);
    const food_type = document.getElementById('edit-prod-foodtype').value.trim();
    const manufacturer = document.getElementById('edit-prod-manufacturer').value.trim();
    const shelf_life_text = document.getElementById('edit-prod-shelflife').value.trim();
    const contents_capacity = document.getElementById('edit-prod-contentscap').value.trim();
    const origin_info = document.getElementById('edit-prod-origin').value.trim();
    const cs_phone = document.getElementById('edit-prod-csphone').value.trim();
    const storage_method = document.getElementById('edit-prod-storage').value.trim();
    const allergy_notice = document.getElementById('edit-prod-allergy').value.trim();

    const options = [];
    document.querySelectorAll('.edit-opt-row').forEach(row => {
        const optName = row.querySelector('.edit-opt-name').value.trim();
        const optPrice = parseInt(row.querySelector('.edit-opt-price').value) || 0;
        const isUnlimited = row.querySelector('.opt-unlimited-chk')?.checked;
        const optStock = isUnlimited ? 999999 : (parseInt(row.querySelector('.edit-opt-stock').value) || 0);
        const optObj = { option_name: optName, additional_price: optPrice, stock: optStock };
        if (row.dataset.optId) optObj.id = parseInt(row.dataset.optId);
        if (optName) options.push(optObj);
    });

    try {
        btnEl.disabled = true;
        const resp = await fetch(`/api/admin/products/${productId}`, {
            method: 'PUT',
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, category_id, price, capacity, description, is_active, food_type, manufacturer, shelf_life_text, contents_capacity, origin_info, cs_phone, storage_method, allergy_notice, options })
        });
        const data = await resp.json();
        if (resp.ok) { customAlert(data.message || '상품 정보가 수정되었습니다.', 'success'); closeModal('editProductModal'); loadProducts(); loadDashboardMetrics(); }
        else customAlert(data.error || '상품 수정 실패', 'error');
    } catch (err) { console.error(err); customAlert('상품 수정 요청 중 오류 발생', 'error'); }
    finally { btnEl.disabled = false; }
}
