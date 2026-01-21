import streamlit as st
import time
import pandas as pd

def show_inventory_ui(db):
    """
    [V218] 소모품 재고관리 시스템 UI - 디버깅 모드
    - 등록 실패 시 정확한 에러 원인 출력
    """
    st.title("📦 소모품 재고관리 센터")
    
    # 상단 메뉴 구성
    tab1, tab2, tab3, tab4 = st.tabs(["📊 재고 현황판", "⚡ 입/출고(현장용)", "⚙️ 품목 등록/관리", "📜 이력 조회"])

    # ------------------------------------------------------------------
    # [Tab 1] 재고 현황판
    # ------------------------------------------------------------------
    with tab1:
        st.markdown("### 🚦 실시간 재고 목록")
        
        # 데이터 조회
        items = db.get_inventory_items()
        
        if not items:
            st.info("등록된 품목이 없습니다. [⚙️ 품목 등록/관리] 탭에서 품목을 등록해주세요.")
        else:
            # 1. 필터링 기능
            cat_list = ["전체"] + sorted(list(set([i['category'] for i in items])))
            selected_cat = st.selectbox("카테고리 필터", cat_list)
            
            # 2. 필터 적용
            display_items = items if selected_cat == "전체" else [i for i in items if i['category'] == selected_cat]
            
            # 3. 테이블 출력 (적정재고 컬럼 제거)
            if display_items:
                df = pd.DataFrame(display_items)
                # min_qty 컬럼을 제외하고 표시
                df_show = df[['category', 'item_name', 'model_name', 'location', 'current_qty']].copy()
                df_show.columns = ['분류', '품명', '규격/모델', '위치', '현재 수량']
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
            # 검색 기능
            search_txt = st.text_input("🔍 품명 또는 모델명 검색", placeholder="예: 시약, 638-...")
            
            target_items = items
            if search_txt:
                target_items = [i for i in items if search_txt.lower() in i['item_name'].lower() or search_txt.lower() in (i['model_name'] or "").lower()]
            
            if not target_items:
                st.warning("검색 결과가 없습니다.")
            
            for item in target_items:
                with st.expander(f"📦 [{item['category']}] {item['item_name']} (현재: {item['current_qty']}개)", expanded=False):
                    st.markdown(f"- **규격:** {item['model_name']} / **위치:** {item.get('location', '-')}")
                    
                    # 입력 폼
                    c_worker, c_qty = st.columns([1, 1])
                    worker = c_worker.text_input("작업자(닉네임)", key=f"w_{item['id']}")
                    qty = c_qty.number_input("수량", min_value=1, value=1, key=f"q_{item['id']}")
                    reason = st.text_input("사유 (선택사항)", placeholder="예: 정기 교체", key=f"r_{item['id']}")
                    
                    b1, b2 = st.columns(2)
                    
                    # [입고] 버튼
                    if b1.button("📥 입고 (+)", key=f"in_{item['id']}", use_container_width=True):
                        if not worker: st.error("작업자 이름을 입력하세요.")
                        else:
                            if db.log_inventory_change(item['id'], "입고", qty, worker, reason):
                                st.success(f"{qty}개 입고 완료!"); time.sleep(0.5); st.rerun()
                            else: st.error("처리 실패")
                    
                    # [출고] 버튼
                    if b2.button("📤 출고 (-)", key=f"out_{item['id']}", use_container_width=True):
                        if not worker: st.error("작업자 이름을 입력하세요.")
                        elif item['current_qty'] < qty: st.error(f"재고가 부족합니다! (현재 {item['current_qty']}개)")
                        else:
                            if db.log_inventory_change(item['id'], "출고", qty, worker, reason):
                                st.success(f"{qty}개 출고 완료!"); time.sleep(0.5); st.rerun()
                            else: st.error("처리 실패")

    # ------------------------------------------------------------------
    # [Tab 3] 품목 등록 및 관리 (디버깅 모드)
    # ------------------------------------------------------------------
    with tab3:
        st.markdown("### ⚙️ 신규 품목 등록 (초기 입고)")
        
        with st.form("add_item_form_v218"):
            st.markdown("#### 1. 품목 기본 정보")
            c1, c2 = st.columns(2)
            cat = c1.selectbox("분류", ["시약", "필터", "튜브/배관", "센서/전극", "기타 소모품"])
            name = c2.text_input("품명 (필수)", placeholder="예: TOC 산화제")
            
            c3, c4 = st.columns(2)
            model = c3.text_input("규격/모델명", placeholder="예: 638-41323")
            loc = c4.text_input("보관 위치", placeholder="예: 시약장 1층")
            
            desc = st.text_input("제조사/비고", placeholder="예: 시마즈")
            
            st.divider()
            
            # [NEW] 초기 재고 및 등록자 정보 입력
            st.markdown("#### 2. 초기 재고 설정 (선택)")
            c5, c6 = st.columns(2)
            reg_worker = c5.text_input("등록자(닉네임)", placeholder="본인 이름 (필수)")
            init_qty = c6.number_input("초기 보유 수량", min_value=0, value=0, help="현재 가지고 있는 수량을 입력하면 자동으로 입고 처리됩니다.")
            
            if st.form_submit_button("💾 품목 및 재고 저장"):
                if name:
                    if not reg_worker:
                        st.error("이력 관리를 위해 등록자 이름은 필수입니다.")
                    else:
                        # ⬇️ 수정된 부분: 성공여부(success)와 메시지(msg)를 같이 받습니다.
                        success, msg = db.add_inventory_item(cat, name, model, loc, desc, init_qty, reg_worker)
                        
                        if success:
                            st.success(f"[{name}] 등록 완료! (초기 재고 {init_qty}개 반영됨)")
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            # ⬇️ 여기서 진짜 에러 이유가 출력됩니다.
                            st.error(f"❌ 등록 실패: {msg}")
                else:
                    st.error("품명은 필수입니다.")
        
        st.divider()
        st.markdown("### 🗑️ 품목 삭제")
        
        del_items = db.get_inventory_items()
        if del_items:
            for d_item in del_items:
                col_d1, col_d2 = st.columns([4, 1])
                col_d1.text(f"[{d_item['category']}] {d_item['item_name']} ({d_item['model_name']})")
                if col_d2.button("삭제", key=f"del_master_{d_item['id']}"):
                    if db.delete_inventory_item(d_item['id']):
                        st.warning("삭제되었습니다."); time.sleep(0.5); st.rerun()

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
