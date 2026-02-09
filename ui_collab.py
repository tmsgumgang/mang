# ui_collab.py
import streamlit as st
import pandas as pd
from datetime import date

def show_collab_ui(db):
    st.title("🤝 협업 공간 (Collab)")

    tab1, tab2 = st.tabs(["📅 월별 일정 (Calendar)", "📞 업체 연락처 (Contacts)"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 관리
    # ------------------------------------------------------------------
    with tab1:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown("### 📆 이달의 주요 일정")
        with c2:
            if st.button("➕ 일정 등록"):
                st.session_state['show_sched_form'] = not st.session_state.get('show_sched_form', False)

        # 일정 등록 폼
        if st.session_state.get('show_sched_form', False):
            with st.form("add_sched_form"):
                st.write("새 일정 추가")
                sc1, sc2 = st.columns(2)
                title = sc1.text_input("일정명 (예: 정기점검)")
                cat = sc2.selectbox("구분", ["점검", "공사", "회의", "휴가", "기타"])
                d1 = sc1.date_input("시작일", date.today())
                d2 = sc2.date_input("종료일", date.today())
                desc = st.text_area("상세 내용")
                author = st.text_input("등록자")
                
                if st.form_submit_button("저장"):
                    if db.add_schedule(title, d1, d2, cat, desc, author):
                        st.success("등록되었습니다.")
                        st.session_state['show_sched_form'] = False
                        st.rerun()

        # 일정 목록 조회
        schedules = db.get_schedules() # 전체 조회 (필요 시 월별 필터 추가 가능)
        if schedules:
            # 캘린더처럼 보이게 하거나 리스트로 출력
            df = pd.DataFrame(schedules)
            df['start_date'] = pd.to_datetime(df['start_date']).dt.date
            df['end_date'] = pd.to_datetime(df['end_date']).dt.date
            
            # 보기 좋게 출력
            for _, row in df.iterrows():
                with st.expander(f"[{row['category']}] {row['start_date']} ~ {row['end_date']} : {row['title']}"):
                    st.write(f"**내용:** {row['description']}")
                    st.write(f"**등록자:** {row['author']}")
                    if st.button("삭제", key=f"del_sched_{row['id']}"):
                        db.delete_schedule(row['id'])
                        st.rerun()
        else:
            st.info("등록된 일정이 없습니다.")

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리
    # ------------------------------------------------------------------
    with tab2:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown("### 📒 업체/담당자 비상 연락망")
        with c2:
            if st.button("➕ 연락처 추가"):
                st.session_state['show_contact_form'] = not st.session_state.get('show_contact_form', False)

        # 연락처 등록 폼
        if st.session_state.get('show_contact_form', False):
            with st.form("add_contact_form"):
                cc1, cc2 = st.columns(2)
                cat = cc1.selectbox("분류", ["제조사", "시약업체", "공사업체", "유관기관", "기타"])
                comp = cc2.text_input("업체명")
                name = cc1.text_input("담당자명")
                phone = cc2.text_input("전화번호")
                email = st.text_input("이메일")
                memo = st.text_area("메모 (주요 취급 품목 등)")
                
                if st.form_submit_button("저장"):
                    if db.add_contact(cat, comp, name, phone, email, memo):
                        st.success("저장되었습니다.")
                        st.session_state['show_contact_form'] = False
                        st.rerun()

        # 연락처 목록
        contacts = db.get_contacts()
        if contacts:
            df_c = pd.DataFrame(contacts)
            # 깔끔한 테이블 뷰
            st.dataframe(
                df_c[['category', 'company_name', 'manager_name', 'phone', 'email', 'memo']],
                column_config={
                    "category": "분류", "company_name": "업체명", "manager_name": "담당자",
                    "phone": "전화번호", "email": "이메일", "memo": "비고"
                },
                use_container_width=True
            )
        else:
            st.info("등록된 연락처가 없습니다.")
