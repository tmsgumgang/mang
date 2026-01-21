import streamlit as st
import time
import pandas as pd

def show_inventory_ui(db):
    """
    [V210] 소모품 재고관리 시스템 UI
    - 탭 1: 재고 부족 알림 및 전체 현황판
    - 탭 2: 현장용 간편 입/출고 (버튼식)
    - 탭 3: 마스터 데이터 관리 (품목 등록/삭제)
    """
    st.title("📦 소모품 재고관리 센터")
    
    # 상단 메뉴 구성
    tab1, tab2, tab3 = st.tabs(["📊 재고 현황판", "⚡ 입/출고(현장용)", "⚙️ 품목 등록/관리"])

    # ------------------------------------------------------------------
    # [Tab 1] 재고 현황판 (Dashboard)
    # ------------------------------------------------------------------
    with tab1:
        st.markdown("### 🚦 실시간 재고 모니터링")
        
        # 데이터 조회
        items = db.get_inventory_items()
        
        if not items:
            st.info("등록된 품목이 없습니다. [⚙️ 품목 등록/관리] 탭에서 품목을 등록해주세요.")
        else:
            # 1. 재고 부족 경고 (RED ZONE)
            shortage_items = [i for i in items if i['current_qty'] <= i['min_qty']]
            
            if shortage_items:
                st.error(f"🚨 **재고 부족 경고: {len(shortage_items)}개 품목** (주문이 필요합니다!)")
                for item in shortage_items:
                    with st.container():
                        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                        c1.markdown(f"**{item['item_name']}**")
                        c2.caption(f"{item['model_name']} ({item['manufacturer'] or '미지정'})")
                        c3.markdown(f"🔴 **{item['current_qty']}**개")
                        c4.caption(f"기준: {item['min_qty']}")
                st.divider()

            # 2. 전체 재고 리스트 (GREEN ZONE)
            st.markdown("#### ✅ 전체 보유 현황")
            
            # 필터링 기능
            cat_list = ["전체"] + sorted(list(set([i['category'] for i in items])))
            selected_cat = st.selectbox("카테고리 필터", cat_list)
            
            # 필터 적용
            display_items = items if selected_cat == "전체" else [i for i in items if i['category'] == selected_cat]
            
            # 테이블 형태로 깔끔하게 보여주기 (Pandas 활용)
            if display_items:
                df = pd.DataFrame(display_items)
                # 컬럼명 한글 매핑
                df_show = df[['category', 'item_name', 'model_name', 'location', 'current_qty', 'min_qty']].copy()
                df_show.columns = ['분류', '품명', '규격/모델', '위치', '현재고', '적정재고']
                st.dataframe(df_show, use_container_width=True, hide_index=True)
            else:
                st.info("해당 카테고리의 품목이 없습니다.")

    # ------------------------------------------------------------------
    # [Tab 2] 간편 입/출고 (Quick Action)
    # ------------------------------------------------------------------
    with tab2:
        st.markdown("### ⚡ 현장 입/출고 처리")
        st.caption("작업자 이름을 입력하고, 수량을 조절한 뒤 버튼을 누르세요.")
        
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
                # 카드 형태의 디자인
                with st.expander(f"📦 [{item['category']}] {item['item_name']} (현재: {item['current_qty']}개)", expanded=False):
                    st.markdown(f"- **규격:** {item['model_name']} / **위치:** {item.get('location', '-')}")
                    
                    # 입력 폼 (Unique Key 필수)
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
                    
                    # [출고] 버튼 (재고 부족 체크)
                    if b2.button("📤 출고 (-)", key=f"out_{item['id']}", use_container_width=True):
                        if not worker: st.error("작업자 이름을 입력하세요.")
                        elif item['current_qty'] < qty: st.error(f"재고가 부족합니다! (현재 {item['current_qty']}개)")
                        else:
                            if db.log_inventory_change(item['id'], "출고", qty, worker, reason):
                                st.success(f"{qty}개 출고 완료!"); time.sleep(0.5); st.rerun()
                            else: st.error("처리 실패")

    # ------------------------------------------------------------------
    # [Tab 3] 품목 등록 및 관리 (Master Data)
    # ------------------------------------------------------------------
    with tab3:
        st.markdown("### ⚙️ 신규 품목 등록")
        
        with st.form("add_item_form"):
            c1, c2 = st.columns(2)
            cat = c1.selectbox("분류", ["시약", "필터", "튜브/배관", "센서/전극", "기타 소모품"])
            name = c2.text_input("품명 (필수)", placeholder="예: TOC 산화제")
            
            c3, c4 = st.columns(2)
            model = c3.text_input("규격/모델명", placeholder="예: 638-41323")
            loc = c4.text_input("보관 위치", placeholder="예: 시약장 1층")
            
            desc = st.text_input("제조사/비고", placeholder="예: 시마즈")
            min_q = st.number_input("적정 재고 (이보다 적으면 경고)", min_value=0, value=5)
            
            if st.form_submit_button("💾 품목 저장"):
                if name:
                    if db.add_inventory_item(cat, name, model, loc, desc, min_q):
                        st.success("등록되었습니다!"); time.sleep(1); st.rerun()
                    else: st.error("등록 실패")
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
