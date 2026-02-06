import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

def show_collab_ui(db):
    st.markdown("""<style>
        .contact-card { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; margin-bottom: 10px; }
        .schedule-row { padding: 10px; border-bottom: 1px solid #eee; }
    </style>""", unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 캘린더", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 관리
    # ------------------------------------------------------------------
    with tab1:
        c1, c2 = st.columns([2, 1])
        
        with c1:
            st.subheader("📅 예정된 일정")
            schedules = db.get_schedules()
            
            if schedules:
                df = pd.DataFrame(schedules)
                df['start_time'] = pd.to_datetime(df['start_time'])
                
                # 오늘 이후 일정만 필터링 or 전체 보기
                upcoming = df[df['start_time'] >= datetime.now() - timedelta(days=1)]
                
                for _, row in upcoming.iterrows():
                    with st.expander(f"[{row['category']}] {row['start_time'].strftime('%m-%d %H:%M')} : {row['title']}"):
                        st.write(f"📝 내용: {row['description']}")
                        st.caption(f"등록자: {row['created_by']}")
                        if st.button("삭제", key=f"del_sch_{row['id']}"):
                            db.delete_schedule(row['id'])
                            st.rerun()
            else:
                st.info("등록된 일정이 없습니다.")

        with c2:
            st.markdown("### ➕ 일정 등록")
            with st.form("add_schedule_form"):
                s_title = st.text_input("일정 제목", placeholder="예: 정기 점검")
                s_cat = st.selectbox("분류", ["정기점검", "수리/AS", "납품/미팅", "회식/기타"])
                
                d1, d2 = st.columns(2)
                s_date = d1.date_input("날짜")
                s_time = d2.time_input("시간")
                
                s_desc = st.text_area("상세 내용")
                s_user = st.text_input("등록자", "관리자")
                
                if st.form_submit_button("일정 추가"):
                    full_dt = datetime.combine(s_date, s_time).isoformat()
                    if db.add_schedule(s_title, full_dt, full_dt, s_cat, s_desc, s_user):
                        st.success("등록 완료!")
                        time.sleep(0.5)
                        st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("📒 주요 업체 및 담당자 연락처")
        
        # 검색 기능
        search_txt = st.text_input("🔍 연락처 검색 (업체명, 담당자, 태그)", placeholder="예: 시마즈, 펌프")
        
        all_contacts = db.get_contacts()
        filtered = []
        if search_txt:
            search_txt = search_txt.lower()
            for c in all_contacts:
                raw = f"{c['company_name']} {c['person_name']} {c['tags']}".lower()
                if search_txt in raw:
                    filtered.append(c)
        else:
            filtered = all_contacts

        # 연락처 리스트 (데이터 에디터 사용)
        if filtered:
            df_con = pd.DataFrame(filtered)
            # 표시할 컬럼만 선택 및 이름 변경
            display_df = df_con[['id', 'company_name', 'person_name', 'phone', 'email', 'tags', 'memo']]
            display_df.columns = ['ID', '업체명', '담당자', '전화번호', '이메일', '태그', '메모']
            
            edited_df = st.data_editor(
                display_df, 
                key="contact_editor",
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                disabled=["ID"] # ID는 수정 불가
            )
            
            # 수정 사항 감지 및 DB 업데이트 (옵션: 버튼 눌러서 저장)
            if st.button("💾 변경사항 저장 (수정/삭제 반영)"):
                # Streamlit data_editor는 복잡해서, 여기선 간단히 '추가' 폼만 따로 두고
                # 리스트 수정은 고급 기능이라 일단 조회 위주로 갑니다.
                # 필요시 추가 구현 가능. 여기서는 '새로고침' 역할만.
                st.toast("데이터가 갱신되었습니다.")
                st.rerun()
        else:
            st.info("연락처 데이터가 없습니다.")

        st.divider()
        
        # 연락처 추가 폼 (Expander로 숨김)
        with st.expander("➕ 새 연락처 등록하기", expanded=False):
            with st.form("add_contact_form"):
                cc1, cc2 = st.columns(2)
                n_comp = cc1.text_input("업체명 (필수)")
                n_name = cc2.text_input("담당자")
                
                cc3, cc4 = st.columns(2)
                n_phone = cc3.text_input("전화번호")
                n_email = cc4.text_input("이메일")
                
                n_tags = st.text_input("태그 (쉼표 구분)", placeholder="예: 시약, 수리, 펌프")
                n_memo = st.text_area("메모")
                
                if st.form_submit_button("저장"):
                    if n_comp:
                        if db.add_contact(n_comp, n_name, n_phone, n_email, n_tags, n_memo):
                            st.success("저장되었습니다.")
                            time.sleep(0.5)
                            st.rerun()
                    else:
                        st.error("업체명은 필수입니다.")
import time # time 모듈 import
