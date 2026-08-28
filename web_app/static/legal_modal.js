/**
 * 영월고향방앗간 2026 법적 준수 약관 & 방침 모달 전문 스크립트
 */

const LEGAL_TEXTS = {
    terms: {
        title: "영월고향방앗간 이용약관",
        content: `
            <div class="info-box" style="background-color: #f9f6f0; border: 1px solid #e5dec9; padding: 1rem; border-radius: 8px; margin-bottom: 1.5rem; font-size: 0.9rem;">
                <p style="margin:0.2rem 0;"><strong>[사업자 및 사이트 기본 정보]</strong></p>
                <p style="margin:0.2rem 0;">• 상호명: 고향방앗간 (대표: 권오명)</p>
                <p style="margin:0.2rem 0;">• 사업자등록번호: 787-04-02840 | 통신판매업신고: 제 2026-강원영월-0000 호</p>
                <p style="margin:0.2rem 0;">• 사업장 주소: 강원특별자치도 영월군 영월읍 절무리골길 16, 제2동 1층</p>
                <p style="margin:0.2rem 0;">• 고객센터: 010-4422-5267 | 이메일: no-reply@yeongwol-gohyangmill.co.kr</p>
                <p style="margin:0.2rem 0;">• 개인정보보호책임자: 권오명</p>
            </div>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제1조 (목적)</h4>
            <p>본 약관은 영월고향방앗간(이하 "회사")이 운영하는 온라인 쇼핑몰(이하 "몰")에서 제공하는 인터넷 관련 서비스의 이용과 관련하여 회사와 이용자의 권리·의무 및 책임사항을 규정함을 목적으로 합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제2조 (정의)</h4>
            <p>1. "몰"이란 회사가 재화 또는 용역을 이용자에게 제공하기 위하여 컴퓨터, 모바일 등의 정보통신설비를 이용하여 재화 등을 거래할 수 있도록 설정한 온라인 영업장을 말합니다.<br>
            2. "이용자"란 몰에 접속하여 본 약관에 따라 회사가 제공하는 서비스를 이용하는 회원 및 비회원을 말합니다.<br>
            3. "회원"이란 몰에 회원등록을 한 자로서 계속적으로 회사가 제공하는 서비스를 이용할 수 있는 자를 말합니다.<br>
            4. "비회원"이란 회원가입 없이 회사가 제공하는 서비스를 이용하는 자를 말합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제3조 (약관의 게시 및 변경)</h4>
            <p>1. 회사는 본 약관의 내용과 상호, 대표자, 사업장 주소, 전화번호, 사업자등록번호, 통신판매업 신고번호 등을 이용자가 쉽게 확인할 수 있도록 몰에 게시합니다.<br>
            2. 회사는 관련 법령을 위반하지 않는 범위에서 본 약관을 개정할 수 있습니다.<br>
            3. 약관을 개정하는 경우 적용일자와 개정사유를 명시하여 적용일 7일 전부터 공지합니다. 이용자에게 불리한 내용으로 변경하는 경우에는 원칙적으로 30일 이상의 사전 유예기간을 두고 공지합니다.<br>
            4. 개정된 약관은 적용일 이후 체결되는 계약부터 적용하며, 그 이전에 체결된 계약은 특별한 사정이 없는 한 기존 약관을 적용합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제4조 (서비스의 제공)</h4>
            <p>회사는 다음 각 호의 서비스를 제공합니다.<br>
            1. 상품에 대한 정보 제공 및 구매계약 체결<br>
            2. 구매계약이 체결된 상품의 배송<br>
            3. 주문, 결제, 배송 및 취소·교환·반품 관리<br>
            4. 회원정보 및 주문내역 관리<br>
            5. 고객문의 및 상담<br>
            6. 기타 회사가 정하는 서비스</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제5조 (서비스의 변경 및 중단)</h4>
            <p>1. 상품의 품절, 생산 중단, 기술적 사양 변경 등의 사유가 있는 경우 회사는 제공할 상품 또는 서비스의 내용을 변경할 수 있습니다.<br>
            2. 정보통신설비의 점검·교체·고장, 통신 장애 또는 기타 불가피한 사유가 있는 경우 서비스 제공을 일시적으로 중단할 수 있습니다.<br>
            3. 주문 완료 후 상품 공급이 불가능한 사실을 확인한 경우 회사는 해당 사실을 지체 없이 이용자에게 알리고 결제대금을 환급하거나 환급에 필요한 조치를 합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제6조 (회원가입)</h4>
            <p>1. 이용자는 회사가 정한 가입양식에 회원정보를 입력하고 본 약관 및 필요한 개인정보 처리에 동의함으로써 회원가입을 신청합니다.<br>
            2. 회사는 다음 각 호에 해당하지 않는 한 회원으로 등록합니다.<br>
            &nbsp;&nbsp;가. 가입 신청 내용에 허위, 기재누락 또는 오기가 있는 경우<br>
            &nbsp;&nbsp;나. 다른 사람의 정보를 도용하여 신청한 경우<br>
            &nbsp;&nbsp;다. 서비스 운영 또는 기술상 회원등록이 현저히 곤란한 경우<br>
            &nbsp;&nbsp;라. 관계 법령 또는 본 약관을 위반할 목적으로 신청한 경우<br>
            3. 회원은 등록한 정보가 변경된 경우 지체 없이 회원정보를 수정하거나 회사에 알려야 합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제7조 (회원탈퇴 및 이용제한)</h4>
            <p>1. 회원은 언제든지 몰에서 회원탈퇴를 요청할 수 있으며 회사는 관련 법령상 보존할 필요가 있는 정보를 제외하고 필요한 절차를 진행합니다.<br>
            2. 회원이 다음 각 호에 해당하는 경우 회사는 서비스 이용을 제한하거나 회원자격을 정지 또는 상실시킬 수 있습니다.<br>
            &nbsp;&nbsp;가. 가입 시 허위정보를 등록한 경우<br>
            &nbsp;&nbsp;나. 다른 이용자의 서비스 이용을 방해하거나 정보를 도용한 경우<br>
            &nbsp;&nbsp;다. 관계 법령 또는 공공질서에 반하는 행위를 한 경우<br>
            &nbsp;&nbsp;라. 부정한 방법으로 결제 또는 서비스를 이용한 경우</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제8조 (구매신청)</h4>
            <p>이용자는 몰에서 다음 또는 이와 유사한 방법으로 구매를 신청합니다.<br>
            1. 상품 검색 및 선택<br>
            2. 주문자 및 배송정보 입력<br>
            3. 상품 가격, 배송비, 교환·반품 조건 등 확인<br>
            4. 이용약관 및 구매조건 확인<br>
            5. 결제수단 선택 및 결제<br>
            6. 주문 내용 최종 확인</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제9조 (구매계약의 성립)</h4>
            <p>1. 회사가 이용자의 구매신청을 승낙하고 주문완료 또는 결제완료 사실을 안내한 시점에 구매계약이 성립합니다.<br>
            2. 다음 각 호에 해당하는 경우 회사는 구매신청을 승낙하지 않거나 계약 성립 이후에도 주문을 취소할 수 있습니다.<br>
            &nbsp;&nbsp;가. 신청 내용에 허위 또는 누락이 있는 경우<br>
            &nbsp;&nbsp;나. 상품이 품절되거나 공급이 불가능한 경우<br>
            &nbsp;&nbsp;다. 시스템 오류 등으로 상품 가격이나 정보가 명백하게 잘못 표시된 경우<br>
            &nbsp;&nbsp;라. 부정결제 또는 비정상적인 거래로 판단할 합리적인 사유가 있는 경우<br>
            3. 이미 결제된 주문을 취소하는 경우 회사는 관련 법령에 따라 결제대금을 환급합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제10조 (결제)</h4>
            <p>1. 회사는 신용카드, 간편결제, 계좌이체 등 회사가 제공하는 결제방법을 이용할 수 있도록 할 수 있습니다.<br>
            2. 결제 과정에서 발생하는 오류 또는 결제서비스 제공업체의 장애 등은 해당 결제수단의 정책에 따라 처리될 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제11조 (상품의 공급 및 배송)</h4>
            <p>1. 회사는 별도의 약정이 없는 경우 주문 및 결제 확인 후 상품 공급을 위해 필요한 절차를 진행합니다.<br>
            2. 배송기간은 상품의 재고, 주문량, 택배사의 사정, 기상상황 및 도서산간 지역 여부 등에 따라 달라질 수 있습니다.<br>
            3. 천재지변, 택배사 사고 등 회사가 합리적으로 통제하기 어려운 사유로 배송이 지연되는 경우 회사는 이용자에게 해당 사실을 안내할 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제12조 (청약철회, 교환 및 반품)</h4>
            <p>1. 이용자는 관계 법령에서 정한 경우 상품을 공급받은 날부터 7일 이내에 청약철회를 신청할 수 있습니다.<br>
            2. 상품이 표시·광고 내용과 다르거나 계약 내용과 다르게 이행된 경우에는 관계 법령에서 정하는 기간 내에 교환·반품 또는 청약철회를 신청할 수 있습니다.<br>
            3. 다음과 같이 이용자에게 책임이 있는 사유로 상품 가치가 현저히 감소한 경우에는 청약철회가 제한될 수 있습니다.<br>
            &nbsp;&nbsp;가. 이용자의 책임으로 상품이 멸실 또는 훼손된 경우<br>
            &nbsp;&nbsp;나. 상품을 사용하거나 일부 소비하여 가치가 현저히 감소한 경우<br>
            &nbsp;&nbsp;다. 시간이 지나 다시 판매하기 곤란할 정도로 가치가 현저히 감소한 경우<br>
            4. 식품 등 시간의 경과에 따라 재판매가 곤란하거나 품질이 현저히 저하될 수 있는 상품은 관계 법령에서 정한 요건에 따라 단순변심에 의한 교환·반품이 제한될 수 있으며, 해당 제한사항은 상품 상세페이지 등에 사전에 안내합니다.<br>
            5. 단순변심에 따른 교환·반품 배송비는 이용자가 부담합니다.<br>
            6. 상품의 하자, 오배송 또는 회사의 귀책사유에 따른 교환·반품 배송비는 회사가 부담합니다.<br>
            7. 자세한 사항은 몰의 "교환·반품·환불 정책"을 따릅니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제13조 (환급)</h4>
            <p>1. 회사는 청약철회 또는 주문취소가 적법하게 이루어진 경우 관계 법령에서 정한 기간 내에 결제대금을 환급하거나 환급에 필요한 조치를 합니다.<br>
            2. 신용카드 등의 결제수단을 이용한 경우 회사는 해당 결제수단 제공사업자에게 결제취소를 요청할 수 있으며 실제 환급 시점은 카드사 또는 결제기관의 처리 일정에 따라 달라질 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제14조 (개인정보보호)</h4>
            <p>1. 회사는 서비스 제공에 필요한 최소한의 개인정보를 처리합니다.<br>
            2. 개인정보의 처리 목적, 항목, 보유기간, 위탁 등의 자세한 사항은 별도의 "개인정보처리방침"에 따릅니다.<br>
            3. 회사는 이용자의 동의 없이 개인정보를 목적 외로 이용하거나 제3자에게 제공하지 않습니다. 다만 관계 법령에 따른 경우는 제외합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제15조 (회사와 이용자의 의무)</h4>
            <p>1. 회사는 관계 법령과 본 약관을 준수하며 안정적인 서비스를 제공하기 위해 노력합니다.<br>
            2. 이용자는 다음 행위를 하여서는 안 됩니다.<br>
            &nbsp;&nbsp;가. 허위정보 등록<br>
            &nbsp;&nbsp;나. 타인의 정보 도용<br>
            &nbsp;&nbsp;다. 몰에 게시된 정보의 무단 변경<br>
            &nbsp;&nbsp;라. 회사가 허용하지 않은 프로그램 등의 전송 또는 게시<br>
            &nbsp;&nbsp;마. 회사 또는 제3자의 저작권 등 권리를 침해하는 행위<br>
            &nbsp;&nbsp;바. 서비스 운영을 방해하는 행위<br>
            &nbsp;&nbsp;사. 관계 법령에 위반되는 행위</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제16조 (저작권)</h4>
            <p>1. 몰에서 제공되는 디자인, 이미지, 텍스트, 로고 등 회사가 제작한 콘텐츠에 대한 저작권 및 기타 지식재산권은 회사 또는 정당한 권리자에게 있습니다.<br>
            2. 이용자는 회사의 사전 승낙 없이 이를 영리 목적으로 복제, 배포, 전송 또는 이용할 수 없습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">제17조 (분쟁해결)</h4>
            <p>1. 회사는 이용자가 제기하는 정당한 의견이나 불만을 처리하기 위해 고객센터를 운영합니다.<br>
            2. 회사와 이용자 사이에 발생한 전자상거래 분쟁에 대하여 관계기관의 조정절차를 이용할 수 있습니다.<br>
            3. 본 약관과 관련한 분쟁에 관한 소송은 관계 법령에서 정한 관할법원에 제기합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">부칙</h4>
            <p>본 약관은 2026년 8월 28일부터 시행합니다.</p>
        `
    },
    privacy: {
        title: "영월고향방앗간 개인정보처리방침",
        content: `
            <p>영월고향방앗간(이하 "회사")은 이용자의 개인정보를 중요하게 생각하며 「개인정보 보호법」 등 관계 법령을 준수하고 있습니다.</p>
            <p>회사는 개인정보 처리방침을 통하여 이용자의 개인정보가 어떠한 목적으로 처리되고 있으며 개인정보 보호를 위해 어떠한 조치가 이루어지고 있는지 안내합니다.</p>

            <div class="info-box" style="background-color: #f9f6f0; border: 1px solid #e5dec9; padding: 1rem; border-radius: 8px; margin: 1rem 0; font-size: 0.9rem;">
                <p style="margin:0.2rem 0;"><strong>[개인정보 보호책임자 지정 안내]</strong></p>
                <p style="margin:0.2rem 0;">• 개인정보 보호책임자: 권오명 대표</p>
                <p style="margin:0.2rem 0;">• 고객센터 전화번호: 010-4422-5267</p>
                <p style="margin:0.2rem 0;">• 개인정보 문의 이메일: no-reply@yeongwol-gohyangmill.co.kr</p>
                <p style="margin:0.2rem 0;">• 사업장 주소: 강원특별자치도 영월군 영월읍 절무리골길 16, 제2동 1층</p>
            </div>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">1. 개인정보의 처리 목적</h4>
            <p>회사는 다음의 목적을 위하여 개인정보를 처리합니다.</p>
            <p><strong>가. 회원관리</strong>: 회원가입 및 본인 식별, 이메일 인증, 회원정보 관리, 비밀번호 재설정, 부정이용 방지, 회원탈퇴 처리<br>
            <strong>나. 주문 및 배송</strong>: 상품 주문 및 결제, 구매자 확인, 상품 배송, 주문 및 배송상태 안내, 취소, 교환, 반품 및 환불 처리<br>
            <strong>다. 고객상담</strong>: 문의사항 접수 및 답변, 민원 및 분쟁 처리<br>
            <strong>라. 마케팅 및 광고 (선택 동의 시)</strong>: 이용자가 별도로 동의한 경우에 한하여 이벤트 및 혜택 안내, 신상품 및 프로모션 안내, 광고성 정보 전송 (동의하지 않아도 서비스 이용 가능)</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">2. 처리하는 개인정보의 항목</h4>
            <p><strong>가. 회원가입</strong>: 이메일, 비밀번호(암호화 저장), 이름, 휴대전화번호<br>
            <strong>나. 주문 및 배송</strong>: 주문자 이름, 휴대전화번호, 이메일, 수령인 이름, 수령인 휴대전화번호, 우편번호, 배송주소, 상세주소, 주문상품 정보, 주문번호, 배송정보<br>
            <strong>다. 결제</strong>: 결제수단, 결제금액, 결제 승인정보, 거래번호 등 결제처리에 필요한 정보 (카드번호 등 인증정보는 결제대행사가 안전 처리하며 직접 저장하지 않음)<br>
            <strong>라. 고객문의 및 교환·반품</strong>: 이름, 연락처, 이메일, 주문번호, 문의내용, 교환·반품·환불 관련 정보<br>
            <strong>마. 자동 수집 항목</strong>: IP 주소, 접속일시, 서비스 이용기록, 브라우저 및 기기정보, 쿠키, 부정이용 기록</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">3. 개인정보의 처리 및 보유기간</h4>
            <p>1. 회사는 개인정보 처리 목적이 달성된 경우 지체 없이 해당 개인정보를 파기합니다. 법령에 따라 보존할 필요가 있는 경우 해당 기간 동안 별도로 안전하게 보관합니다.<br>
            2. <strong>회원정보</strong>: 회원탈퇴 시까지 보관합니다.<br>
            3. <strong>전자상거래 관련 법정 보존정보</strong>:<br>
            &nbsp;&nbsp;• 계약 또는 청약철회 등에 관한 기록: <strong>5년</strong> (전자상거래법)<br>
            &nbsp;&nbsp;• 대금결제 및 상품 공급에 관한 기록: <strong>5년</strong> (전자상거래법)<br>
            &nbsp;&nbsp;• 소비자의 불만 또는 분쟁처리에 관한 기록: <strong>3년</strong> (전자상거래법)<br>
            &nbsp;&nbsp;• 표시·광고에 관한 기록: <strong>6개월</strong> (전자상거래법)</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">4. 개인정보의 제3자 제공</h4>
            <p>회사는 원칙적으로 이용자의 사전 동의 없이 개인정보를 제3자에게 제공하지 않습니다. 다만 법률에 특별한 규정이 있거나 법령상 의무 준수를 위해 필요한 경우는 예외로 합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">5. 개인정보 처리업무의 위탁 (수탁업체)</h4>
            <p>회사는 원활한 서비스 제공을 위해 다음과 같이 개인정보 처리업무를 외부 전문업체에 위탁하여 운영하고 있습니다.</p>
            <table style="width:100%; border-collapse:collapse; margin:0.8rem 0; font-size:0.88rem;">
                <tr style="background:#f5f5f5;">
                    <th style="border:1px solid #ddd; padding:6px 10px;">수탁업체</th>
                    <th style="border:1px solid #ddd; padding:6px 10px;">위탁업무 내용</th>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>포트원 (PortOne / PG사 연동)</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">결제 처리 및 결제정보 연동 (신용카드, 간편결제 등)</td>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>우체국택배 (EPOST Delivery)</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">상품 배송, 위치 추적 및 배송 완료 알림</td>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>가비아 하이웍스 (Hiworks)</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">회원가입 인증, 주문 및 서비스 안내 이메일 발송</td>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>알리고 (Aligo)</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">주문·배송 안내 카카오 알림톡/SMS 및 동의 광고성 정보 발송</td>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>고향방앗간 자사 호스팅</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">서버 및 데이터베이스 보관·안전운영</td>
                </tr>
            </table>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">6. 개인정보의 파기</h4>
            <p>1. 보유기간 경과 또는 처리 목적 달성 시 지체 없이 파기합니다.<br>
            2. 전자적 파일 형태는 복구할 수 없는 방법으로 파기하며 종이 문서는 분쇄 또는 소각합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">7. 이용자와 법정대리인의 권리 및 행사방법</h4>
            <p>이용자는 언제든지 개인정보 열람, 정정·삭제, 처리정지 요구, 회원탈퇴, 마케팅 수신동의 철회의 권리를 행사할 수 있으며 마이페이지 또는 고객센터를 통해 신청하실 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">8. 개인정보의 안전성 확보조치</h4>
            <p>개인정보 접근권한 최소화, 비밀번호 암호화, 접근기록 관리, 해킹 대비 보안조치 등을 적용하고 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">9. 쿠키의 사용</h4>
            <p>로그인 상태 유지 및 이용환경 개선을 위해 쿠키를 사용하며 웹브라우저 설정을 통해 거부할 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">10. 개인정보 보호책임자</h4>
            <p>• 개인정보 보호책임자: 권오명 대표<br>
            • 전화번호: 010-4422-5267<br>
            • 이메일: no-reply@yeongwol-gohyangmill.co.kr</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">11. 개인정보 침해 관련 상담 및 신고</h4>
            <p>• 개인정보침해 신고센터: (국번없이) 118 (privacy.kisa.or.kr)<br>
            • 개인정보분쟁조정위원회: 1833-6972 (www.kopico.go.kr)<br>
            • 경찰청 사이버범죄신고시스템: (국번없이) 182 (ecrm.police.go.kr)</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">12. 개인정보처리방침 변경</h4>
            <p>• 공고일자: 2026년 8월 28일<br>
            • 시행일자: 2026년 8월 28일</p>
        `
    },
    refund: {
        title: "영월고향방앗간 교환·반품·환불 정책",
        content: `
            <p>영월고향방앗간은 「전자상거래 등에서의 소비자보호에 관한 법률」 등 관계 법령에 따라 교환·반품 및 환불을 처리합니다.</p>

            <div class="info-box" style="background-color: #f9f6f0; border: 1px solid #e5dec9; padding: 1rem; border-radius: 8px; margin: 1rem 0; font-size: 0.9rem;">
                <p style="margin:0.2rem 0;"><strong>[반품 접수 및 고객센터 정보]</strong></p>
                <p style="margin:0.2rem 0;">• 상호: 영월고향방앗간 (대표: 권오명)</p>
                <p style="margin:0.2rem 0;">• 반품 주소: 강원특별자치도 영월군 영월읍 절무리골길 16, 제2동 1층</p>
                <p style="margin:0.2rem 0;">• 고객센터 전화번호: 010-4422-5267 (운영시간: 평일 09:00 ~ 18:00)</p>
                <p style="margin:0.2rem 0;">• 이메일: no-reply@yeongwol-gohyangmill.co.kr</p>
            </div>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">1. 주문취소</h4>
            <p><strong>가. 상품 발송 전</strong>: 상품 출고 전에는 주문내역에서 취소를 신청하거나 고객센터를 통해 주문취소를 요청할 수 있습니다. 이미 배송 준비 또는 출고가 완료된 경우 반품 절차로 처리될 수 있습니다.<br>
            <strong>나. 품절 또는 공급 불가</strong>: 결제 완료 후 품절 등으로 공급이 불가능한 경우 고객에게 안내 후 결제대금을 환불합니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">2. 단순변심에 의한 교환·반품</h4>
            <p>1. 상품을 공급받은 날부터 <strong>7일 이내</strong>에 청약철회를 신청할 수 있습니다.<br>
            2. 단순변심에 따른 교환·반품 배송비는 <strong>구매자가 부담</strong>합니다.<br>
            3. 제주·도서산간 지역 추가배송비는 실제 발생한 추가비용이 부과될 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">3. 상품 하자 및 오배송</h4>
            <p>1. 상품 하자, 오배송, 파손의 경우 회사가 배송비를 부담하여 교환·반품 또는 환불을 처리합니다.<br>
            2. 표시·광고 내용과 다르거나 계약 내용과 다르게 이행된 경우 공급받은 날부터 <strong>3개월 이내</strong>, 그 사실을 안 날 또는 알 수 있었던 날부터 <strong>30일 이내</strong> 청약철회가 가능합니다.<br>
            3. 빠른 확인을 위해 상품 및 포장상태 촬영 사진을 전달해 주시면 신속히 처리해 드립니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">4. 교환·반품이 제한될 수 있는 경우</h4>
            <p>• 구매자 책임으로 상품이 멸실 또는 훼손된 경우 (단, 내용 확인을 위한 포장 개봉 제외)<br>
            • 상품을 사용하거나 일부 소비하여 가치가 현저히 감소한 경우<br>
            • 시간이 지나 다시 판매하기 곤란할 정도로 상품 가치가 현저히 감소한 경우<br>
            • 개별 생산/가공되어 재판매가 현저히 곤란한 상품으로서 관련 법령 요건에 따라 사전에 안내하고 동의를 받은 경우</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">5. 식품의 교환·반품</h4>
            <p>영월고향방앗간에서 판매하는 식품(참기름, 들기름, 고춧가루 등)은 보관상태와 시간 경과에 따라 품질이 변할 수 있습니다.<br>
            따라서 상품을 개봉하여 일부 섭취하였거나 보관 부주의로 변질된 경우, 수령 후 시간이 지나 재판매가 곤란한 경우 단순변심 교환·반품이 제한될 수 있습니다.<br>
            다만 제품 자체의 하자, 변질, 오배송 등 회사의 귀책사유가 있는 경우 제한 없이 교환·반품 및 환불 조치해 드립니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">6. 교환·반품 신청방법</h4>
            <p>• 마이페이지 → 주문내역 → 교환/반품 신청<br>
            • 고객센터: 010-4422-5267 | 이메일: no-reply@yeongwol-gohyangmill.co.kr<br>
            *사전 접수 없이 상품을 임의 발송하는 경우 처리가 지연될 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">7. 반품 주소</h4>
            <p>• 상호: 영월고향방앗간<br>
            • 반품 주소: 강원특별자치도 영월군 영월읍 절무리골길 16, 제2동 1층<br>
            • 연락처: 010-4422-5267</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">8. 환불 소요 기간</h4>
            <p>1. 반품 상품이 회사에 도착하여 확인된 후 <strong>3영업일 이내</strong>에 환불 또는 결제취소 절차를 진행합니다.<br>
            2. 신용카드/간편결제 취소 시 카드 승인취소까지 3~5 영업일이 소요될 수 있습니다.</p>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">9. 배송비 부담 기준</h4>
            <table style="width:100%; border-collapse:collapse; margin:0.8rem 0; font-size:0.88rem;">
                <tr style="background:#f5f5f5;">
                    <th style="border:1px solid #ddd; padding:6px 10px;">구분</th>
                    <th style="border:1px solid #ddd; padding:6px 10px;">사유</th>
                    <th style="border:1px solid #ddd; padding:6px 10px;">배송비 부담 주체</th>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>구매자 부담</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">단순변심, 주문 실수, 주소 오기재 등 구매자 귀책 사유</td>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>구매자 부담</strong> (왕복 배송비)</td>
                </tr>
                <tr>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>회사 부담</strong></td>
                    <td style="border:1px solid #ddd; padding:6px 10px;">상품 하자, 파손, 변질, 오배송, 표시·광고 내용과 다른 배송</td>
                    <td style="border:1px solid #ddd; padding:6px 10px;"><strong>고향방앗간 부담</strong> (전액 무료)</td>
                </tr>
            </table>

            <h4 style="color:#915a28; margin-top:1.4rem; font-size:1.05rem;">10. 기타</h4>
            <p>본 정책에서 정하지 않은 사항은 「전자상거래 등에서의 소비자보호에 관한 법률」 등 관계 법령을 우선 적용합니다.<br>
            • 시행일자: 2026년 8월 28일</p>
        `
    }
};

// 모달 DOM 생성 및 이벤트 바인딩
function initLegalModal() {
    if (document.getElementById('legalModalOverlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'legalModalOverlay';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(4px);
        z-index: 99999; display: none; align-items: center; justify-content: center;
        padding: 20px; box-sizing: border-box;
    `;

    overlay.innerHTML = `
        <div style="
            background: #ffffff; width: 100%; max-width: 850px; max-height: 85vh;
            border-radius: 12px; box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            display: flex; flex-direction: column; overflow: hidden; font-family: 'Noto Sans KR', sans-serif;
        ">
            <div style="
                padding: 1.2rem 1.5rem; border-bottom: 1px solid #eee;
                display: flex; justify-content: space-between; align-items: center;
                background: #fdfbf7;
            ">
                <h3 id="legalModalTitle" style="font-family: 'Noto Serif KR', serif; color: #915a28; margin: 0; font-size: 1.25rem;">약관 안내</h3>
                <button id="legalModalCloseBtn" style="
                    background: none; border: none; font-size: 1.5rem; color: #777;
                    cursor: pointer; line-height: 1; padding: 4px 8px; border-radius: 4px;
                ">&times;</button>
            </div>
            <div id="legalModalBody" style="
                padding: 1.5rem 1.8rem; overflow-y: auto; line-height: 1.75; color: #333; font-size: 0.93rem;
            ">
            </div>
            <div style="
                padding: 1rem 1.5rem; border-top: 1px solid #eee; text-align: right; background: #fafafa;
            ">
                <button id="legalModalConfirmBtn" style="
                    background: #915a28; color: #fff; border: none; padding: 0.6rem 1.5rem;
                    border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 0.9rem;
                ">확인</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    const closeBtn = document.getElementById('legalModalCloseBtn');
    const confirmBtn = document.getElementById('legalModalConfirmBtn');

    closeBtn.addEventListener('click', closeLegalModal);
    confirmBtn.addEventListener('click', closeLegalModal);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeLegalModal();
    });
}

function openLegalModal(type) {
    initLegalModal();
    const data = LEGAL_TEXTS[type];
    if (!data) return;

    document.getElementById('legalModalTitle').innerText = data.title;
    document.getElementById('legalModalBody').innerHTML = data.content;

    const overlay = document.getElementById('legalModalOverlay');
    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeLegalModal() {
    const overlay = document.getElementById('legalModalOverlay');
    if (overlay) {
        overlay.style.display = 'none';
        document.body.style.overflow = '';
    }
}

// Global 함수 노출
window.openLegalModal = openLegalModal;
window.closeLegalModal = closeLegalModal;

// DOM 로드 시 자동으로 초기화 준비
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLegalModal);
} else {
    initLegalModal();
}
