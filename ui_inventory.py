import streamlit as st
import time
import pandas as pd

def show_inventory_ui(db):
    """
    [V226] 소모품 재고관리 시스템 UI - 엑셀 다운로드 기능 추가
    1. Tab 1: '엑셀용 파일 다운로드' 버튼 추가 (한글 깨짐 방지 utf-8-sig 적용)
    2. Tab 3: 스마트 업로드(중복 갱신) 로직 유지
    """
    st.title("📦 소모품 재고관리 센터")
    
    # 상단 메뉴 구성
    tab1, tab2, tab3, tab4 = st.tabs(["📊 재고 현황판", "⚡ 입/출고(현장용)", "⚙️ 품목 등록/관리", "📜 이력 조회"])

    # ------------------------------------------------------------------
    # [Tab 1] 재고 현황판
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
                
                # 컬럼 안전 처리
                if 'manufacturer' not in df.columns: df['manufacturer'] = '-'
                if 'measurement_item' not in df.columns: df['measurement_item'] = '-'

                # 보여줄 컬럼 선택 및 한글 이름 변경
                df_show = df[['manufacturer', 'measurement_item', 'model_name', 'item_name', 'location', 'current_qty']].copy()
                df_show.columns = ['제조사', '측정항목', '규격/모델', '품명', '위치', '현재 수량']
                
                # 1. 화면에 표 출력
                st.dataframe(df_show, use_container_width=True, hide_index=True)
                
                # 2. [NEW] 엑셀 다운로드 버튼 추가
                # utf-8-sig 인코딩을 사용하여 엑셀에서 한글이 깨지지 않게 함
                csv = df_show.to_csv(index=False).encode('utf-8-sig')
                
                st.download_button(
                    label="📥 엑셀용 파일 다운로드 (한글 깨짐 방지)",
                    data=csv,
                    file_name='전체_재고_현황.csv',
                    mime='text/csv',
                )
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
                    mfr = item.get('manufacturer') or '-'
                    measure = item.get('measurement_item') or '공통'
                    st.markdown(f"- **제조사:** {mfr} / **측정항목:** {measure}")
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
    # [Tab 3] 품목 등록 및 관리 (스마트 업로드)
    # ------------------------------------------------------------------
    with tab3:
        sub_tab1, sub_tab2 = st.tabs(["📝 개별 등록", "📂 엑셀 일괄 업로드"])
        
        # [3-1] 개별 등록
        with sub_tab1:
            st.markdown("### ⚙️ 신규 품목 등록 (초기 입고)")
            with st.form("add_item_form_v225"):
                st.markdown("#### 1. 품목 기본 정보")
                c1, c2 = st.columns(2)
                cat = c1.selectbox("분류", ["시약", "필터", "튜브/배관", "센서/전극", "기타 소모품"])
                name = c2.text_input("품명 (필수)", placeholder="예: TOC 산화제")
                
                c3, c4 = st.columns(2)
                measure_val = c3.selectbox("측정항목", ["공통", "TOC", "TN", "TP", "일반항목", "VOCs", "기타"])
                model = c4.text_input("규격/모델명", placeholder="예: 638-41323")
                
                c5, c6 = st.columns(2)
                mfr = c5.text_input("제조사", placeholder="예: 시마즈")
                loc = c6.text_input("보관 위치", placeholder="예: 시약장 1층")
                
                st.divider()
                st.markdown("#### 2. 초기 재고 설정 (선택)")
                c7, c8 = st.columns(2)
                reg_worker = c7.text_input("등록자(닉네임)", placeholder="본인 이름 (필수)")
                init_qty = c8.number_input("초기 보유 수량", min_value=0, value=0)
                
                if st.form_submit_button("💾 품목 및 재고 저장"):
                    if name:
                        if not reg_worker: st.error("이력 관리를 위해 등록자 이름은 필수입니다.")
                        else:
                            result = db.add_inventory_item(cat, name, model, loc, mfr, measure_val, init_qty, reg_worker)
                            
                            if isinstance(result, bool): success, msg = result, "알 수 없는 오류"
                            else: success, msg = result
                            
                            if success:
                                st.success(f"[{name}] 등록 완료! (초기 재고 {init_qty}개 반영됨)"); time.sleep(1.5); st.rerun()
                            else: st.error(f"❌ 등록 실패: {msg}")
                    else: st.error("품명은 필수입니다.")

        # [3-2] 엑셀 일괄 업로드 (스마트 갱신 로직 적용)
        with sub_tab2:
            st.markdown("### 📂 엑셀/CSV 파일로 한 번에 등록/갱신하기")
            st.info("💡 엑셀의 수량으로 **덮어쓰기(갱신)** 됩니다. (차이만큼 입/출고 자동 기록)")
            
            with st.expander("📋 엑셀 양식 확인하기 (클릭)", expanded=False):
                st.markdown("""
                **엑셀 첫 줄(헤더)에 아래 단어가 포함되어야 합니다:**
                - `분류`, `품명`(필수), `규격`(식별용), `위치`
                - `제조사`, `측정항목`
                - `초기수량` (이 값으로 재고가 변경됩니다)
                """)
            
            uploaded_file = st.file_uploader("파일 선택", type=['xlsx', 'xls', 'csv'])
            
            if uploaded_file:
                try:
                    if uploaded_file.name.endswith('.csv'):
                        try: df_upload = pd.read_csv(uploaded_file, encoding='utf-8')
                        except: uploaded_file.seek(0); df_upload = pd.read_csv(uploaded_file, encoding='cp949')
                    else: df_upload = pd.read_excel(uploaded_file)
                    
                    st.write("📊 데이터 미리보기 (상위 3개):", df_upload.head(3))
                    
                    expected_cols = {
                        '분류': 'category', '품명': 'item_name', '규격': 'model_name', 
                        '모델': 'model_name', '위치': 'location', 
                        '제조사': 'manufacturer', '브랜드': 'manufacturer', 
                        '측정항목': 'measurement_item', '측정': 'measurement_item', '항목': 'measurement_item', 
                        '초기수량': 'qty', '수량': 'qty'
                    }
                    df_upload.rename(columns=expected_cols, inplace=True)
                    
                    if 'item_name' not in df_upload.columns:
                        st.error("❌ '품명' 열을 찾을 수 없습니다.")
                    else:
                        batch_worker = st.text_input("등록자(닉네임) 입력", placeholder="업로드하는 사람 이름")
                        
                        if st.button("🚀 일괄 등록 및 갱신 시작"):
                            if not batch_worker: st.error("등록자 이름을 입력해주세요.")
                            else:
                                success_count = 0
                                update_count = 0
                                fail_count = 0
                                progress_bar = st.progress(0)
                                total_rows = len(df_upload)
                                
                                for idx, row in df_upload.iterrows():
                                    cat = row.get('category', '기타 소모품') if not pd.isna(row.get('category')) else '기타 소모품'
                                    name = str(row.get('item_name')).strip()
                                    if not name or name == 'nan': continue 
                                    
                                    model = str(row.get('model_name', '')).strip() if not pd.isna(row.get('model_name')) else ''
                                    loc = str(row.get('location', '')).strip() if not pd.isna(row.get('location')) else ''
                                    mfr = str(row.get('manufacturer', '')).strip() if not pd.isna(row.get('manufacturer')) else ''
                                    measure_val = str(row.get('measurement_item', '공통')).strip() if not pd.isna(row.get('measurement_item')) else '공통'
                                    qty = int(row.get('qty', 0)) if not pd.isna(row.get('qty')) else 0
                                    
                                    # [핵심] 1. 중복 확인 (품명 + 규격)
                                    existing_item = db.check_item_exists(name, model)
                                    
                                    if existing_item:
                                        # [핵심] 2. 있으면 수량 갱신 (Update)
                                        res, _ = db.update_inventory_qty(existing_item['id'], qty, batch_worker)
                                        if res: update_count += 1
                                        else: fail_count += 1
                                    else:
                                        # [핵심] 3. 없으면 신규 등록 (Insert)
                                        res = db.add_inventory_item(cat, name, model, loc, mfr, measure_val, qty, batch_worker)
                                        if isinstance(res, tuple) and res[0]: success_count += 1
                                        elif isinstance(res, bool) and res: success_count += 1
                                        else: fail_count += 1
                                    
                                    progress_bar.progress((idx + 1) / total_rows)
                                
                                st.success(f"✅ 작업 완료! (신규: {success_count}건, 갱신: {update_count}건, 실패: {fail_count}건)")
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
