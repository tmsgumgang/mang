import streamlit as st
import time
import pandas as pd

def show_inventory_ui(db):
    """
    [V222] 소모품 재고관리 시스템 UI - 최종 통합본
    1. Tab 1: 대시보드 컬럼 최적화 (제조사 위주)
    2. Tab 3: 엑셀/CSV 일괄 업로드 기능 추가 (사내 보안망 대응)
    3. 안전장치: DB 서비스 버전 호환성 체크 포함
    """
    st.title("📦 소모품 재고관리 센터")
    
    # 상단 메뉴 구성
    tab1, tab2, tab3, tab4 = st.tabs(["📊 재고 현황판", "⚡ 입/출고(현장용)", "⚙️ 품목 등록/관리", "📜 이력 조회"])

    # ------------------------------------------------------------------
    # [Tab 1] 재고 현황판 (개편됨)
    # ------------------------------------------------------------------
    with tab1:
        st.markdown("### 🚦 실시간 재고 목록")
        items = db.get_inventory_items()
        
        if not items:
            st.info("등록된 품목이 없습니다. [⚙️ 품목 등록/관리] 탭에서 품목을 등록해주세요.")
        else:
            cat_list = ["전체"] + sorted(list(set([i['category'] for i in items])))
            selected_cat = st.selectbox("카테고리 필터", cat_list)
            display_items = items if selected_cat == "전체" else [i for i in items if i['category'] == selected_cat]
            
            if display_items:
                df = pd.DataFrame(display_items)
                
                # [수정] 대시보드 컬럼 개편
                # 제조사(description) -> 규격(model_name) -> 품명(item_name) -> 위치 -> 수량
                df_show = df[['description', 'model_name', 'item_name', 'location', 'current_qty']].copy()
                df_show.columns = ['제조사', '규격/모델', '품명', '위치', '현재 수량']
                
                st.dataframe(df_show, use_container_width=True, hide_index=True)
            else:
                st.info("해당 카테고리의 품목이 없습니다.")

    # ------------------------------------------------------------------
    # [Tab 2] 간편 입/출고
    # ------------------------------------------------------------------
    with tab2:
        st.markdown("### ⚡ 현장 입/출고 처리")
        items = db.get_inventory_items()
        if not items:
            st.warning("품목을 먼저 등록해주세요.")
        else:
            search_txt = st.text_input("🔍 품명 또는 모델명 검색", placeholder="예: 시약, 638-...")
            target_items = items
            if search_txt:
                target_items = [i for i in items if search_txt.lower() in i['item_name'].lower() or search_txt.lower() in (i['model_name'] or "").lower()]
            
            if not target_items: st.warning("검색 결과가 없습니다.")
            
            for item in target_items:
                with st.expander(f"📦 [{item['category']}] {item['item_name']} (현재: {item['current_qty']}개)", expanded=False):
                    st.markdown(f"- **규격:** {item['model_name']} / **위치:** {item.get('location', '-')}")
                    
                    c_worker, c_qty = st.columns([1, 1])
                    worker = c_worker.text_input("작업자(닉네임)", key=f"w_{item['id']}")
                    qty = c_qty.number_input("수량", min_value=1, value=1, key=f"q_{item['id']}")
                    reason = st.text_input("사유 (선택사항)", placeholder="예: 정기 교체", key=f"r_{item['id']}")
                    
                    b1, b2 = st.columns(2)
                    
                    if b1.button("📥 입고 (+)", key=f"in_{item['id']}", use_container_width=True):
                        if not worker: st.error("작업자 이름을 입력하세요.")
                        else:
                            if db.log_inventory_change(item['id'], "입고", qty, worker, reason):
                                st.success(f"{qty}개 입고 완료!"); time.sleep(0.5); st.rerun()
                            else: st.error("처리 실패")
                    
                    if b2.button("📤 출고 (-)", key=f"out_{item['id']}", use_container_width=True):
                        if not worker: st.error("작업자 이름을 입력하세요.")
                        elif item['current_qty'] < qty: st.error(f"재고가 부족합니다! (현재 {item['current_qty']}개)")
                        else:
                            if db.log_inventory_change(item['id'], "출고", qty, worker, reason):
                                st.success(f"{qty}개 출고 완료!"); time.sleep(0.5); st.rerun()
                            else: st.error("처리 실패")

    # ------------------------------------------------------------------
    # [Tab 3] 품목 등록 및 관리 (개별 등록 + 엑셀 일괄 업로드)
    # ------------------------------------------------------------------
    with tab3:
        # 탭 분리: 개별 등록 / 엑셀 일괄 업로드
        sub_tab1, sub_tab2 = st.tabs(["📝 개별 등록", "📂 엑셀 일괄 업로드"])
        
        # [3-1] 개별 등록
        with sub_tab1:
            st.markdown("### ⚙️ 신규 품목 등록 (초기 입고)")
            with st.form("add_item_form_v222"):
                st.markdown("#### 1. 품목 기본 정보")
                c1, c2 = st.columns(2)
                cat = c1.selectbox("분류", ["시약", "필터", "튜브/배관", "센서/전극", "기타 소모품"])
                name = c2.text_input("품명 (필수)", placeholder="예: TOC 산화제")
                
                c3, c4 = st.columns(2)
                model = c3.text_input("규격/모델명", placeholder="예: 638-41323")
                loc = c4.text_input("보관 위치", placeholder="예: 시약장 1층")
                desc = st.text_input("제조사/비고", placeholder="예: 시마즈")
                
                st.divider()
                st.markdown("#### 2. 초기 재고 설정 (선택)")
                c5, c6 = st.columns(2)
                reg_worker = c5.text_input("등록자(닉네임)", placeholder="본인 이름 (필수)")
                init_qty = c6.number_input("초기 보유 수량", min_value=0, value=0)
                
                if st.form_submit_button("💾 품목 및 재고 저장"):
                    if name:
                        if not reg_worker: st.error("이력 관리를 위해 등록자 이름은 필수입니다.")
                        else:
                            # DB 통신 및 결과 타입 체크 (안전장치)
                            result = db.add_inventory_item(cat, name, model, loc, desc, init_qty, reg_worker)
                            
                            if isinstance(result, bool):
                                success, msg = result, "알 수 없는 오류"
                            else:
                                success, msg = result
                            
                            if success:
                                st.success(f"[{name}] 등록 완료! (초기 재고 {init_qty}개 반영됨)")
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.error(f"❌ 등록 실패: {msg}")
                    else: st.error("품명은 필수입니다.")

        # [3-2] 엑셀 일괄 업로드 (NEW)
        with sub_tab2:
            st.markdown("### 📂 엑셀/CSV 파일로 한 번에 등록하기")
            st.info("💡 엑셀(.xlsx) 또는 CSV 파일을 업로드하세요. 한글이 깨져도 괜찮습니다.")
            
            with st.expander("📋 엑셀 양식 확인하기 (클릭)", expanded=False):
                st.markdown("""
                **엑셀 첫 줄(헤더)에 아래 단어가 포함되어야 합니다:**
                - `분류`, `품명`(필수), `규격`, `위치`, `제조사`, `초기수량`
                """)
            
            uploaded_file = st.file_uploader("파일 선택", type=['xlsx', 'xls', 'csv'])
            
            if uploaded_file:
                try:
                    # 파일 읽기 (인코딩 자동 처리)
                    if uploaded_file.name.endswith('.csv'):
                        try:
                            df_upload = pd.read_csv(uploaded_file, encoding='utf-8')
                        except:
                            uploaded_file.seek(0)
                            df_upload = pd.read_csv(uploaded_file, encoding='cp949')
                    else:
                        df_upload = pd.read_excel(uploaded_file)
                    
                    st.write("📊 데이터 미리보기 (상위 3개):", df_upload.head(3))
                    
                    # 컬럼 매핑 (한글 -> 영문)
                    expected_cols = {
                        '분류': 'category', '품명': 'item_name', '규격': 'model_name', 
                        '모델': 'model_name', '위치': 'location', '제조사': 'description',
                        '비고': 'description', '초기수량': 'qty', '수량': 'qty'
                    }
                    df_upload.rename(columns=expected_cols, inplace=True)
                    
                    if 'item_name' not in df_upload.columns:
                        st.error("❌ '품명' 열을 찾을 수 없습니다. 엑셀 헤더를 확인해주세요.")
                    else:
                        batch_worker = st.text_input("등록자(닉네임) 입력", placeholder="업로드하는 사람 이름")
                        
                        if st.button("🚀 위 목록을 DB에 일괄 등록"):
                            if not batch_worker:
                                st.error("등록자 이름을 입력해주세요.")
                            else:
                                success_count = 0
                                fail_count = 0
                                progress_bar = st.progress(0)
                                total_rows = len(df_upload)
                                
                                for idx, row in df_upload.iterrows():
                                    # 결측치(NaN) 안전 처리
                                    cat = row.get('category', '기타 소모품') if not pd.isna(row.get('category')) else '기타 소모품'
                                    name = row.get('item_name')
                                    if pd.isna(name): continue # 품명 없으면 패스
                                    
                                    model = row.get('model_name', '') if not pd.isna(row.get('model_name')) else ''
                                    loc = row.get('location', '') if not pd.isna(row.get('location')) else ''
                                    desc = row.get('description', '') if not pd.isna(row.get('description')) else ''
                                    qty = row.get('qty', 0) if not pd.isna(row.get('qty')) else 0
                                    
                                    # DB 등록
                                    res = db.add_inventory_item(str(cat), str(name), str(model), str(loc), str(desc), int(qty), batch_worker)
                                    
                                    # 결과 확인
                                    is_success = False
                                    if isinstance(res, tuple) and res[0]: is_success = True
                                    elif isinstance(res, bool) and res: is_success = True
                                    
                                    if is_success: success_count += 1
                                    else: fail_count += 1
                                    
                                    progress_bar.progress((idx + 1) / total_rows)
                                
                                st.success(f"✅ 완료! 성공: {success_count}건, 실패: {fail_count}건")
                                time.sleep(2)
                                st.rerun()

                except Exception as e:
                    st.error(f"파일 처리 중 에러 발생: {e}")

    # ------------------------------------------------------------------
    # [Tab 4] 이력 조회 (Logs)
    # ------------------------------------------------------------------
    with tab4:
        st.markdown("### 📜 입/출고 전체 이력")
        if st.button("🔄 새로고침", key="refresh_logs"):
            st.rerun()
            
        logs = db.get_inventory_logs()
        if logs:
            for log in logs:
                item_name = log['inventory_items']['item_name'] if log.get('inventory_items') else "삭제된 품목"
                icon = "📥" if log['change_type'] == "입고" else "📤" if log['change_type'] == "출고" else "🔄"
                color = "blue" if log['change_type'] == "입고" else "red" if log['change_type'] == "출고" else "green"
                
                st.markdown(f"""
                <div style="padding:10px; border-bottom:1px solid #eee;">
                    <span style="font-size:1.1rem;">{icon} <strong>{item_name}</strong></span> 
                    <span style="font-size:0.8rem; color:gray;">({log['created_at'][:16].replace('T', ' ')})</span><br>
                    <span style="color:{color}; font-weight:bold;">{log['change_type']} {log['quantity']}개</span> 
                    by <strong>{log['worker_name']}</strong> <span style="color:gray;">- {log.get('reason') or ''}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("아직 기록된 이력이 없습니다.")
