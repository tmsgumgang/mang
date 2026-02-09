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
                    # [수정] DB 함수 인자 개수(location, assignee)를 맞춰주어 에러 방지
                    res = db.add_schedule(title, d1, d2, cat, desc, author, location="현장", assignee=author)
                    
                    # 결과가 튜플일 경우와 불리언일 경우 모두 처리
                    is_success = res[0] if isinstance(res, tuple) else res
                    
                    if is_success:
                        st.success("등록되었습니다.")
                        st.session_state['show_sched_form'] = False
                        st.rerun()
                    else:
                        st.error("등록 실패")

        # 일정 목록 조회
        schedules = db.get_schedules() 
        if schedules:
            df = pd.DataFrame(schedules)
            
            # [핵심 수정] errors='coerce' 추가 -> 날짜 형식이 깨진 데이터가 있어도 무시하고 진행
            if 'start_time' in df.columns:
                df['start_date'] = pd.to_datetime(df['start_time'], errors='coerce').dt.date
            if 'end_time' in df.columns:
                df['end_date'] = pd.to_datetime(df['end_time'], errors='coerce').dt.date
            
            # 날짜 변환 실패로 NaT(결측치)가 된 행 제거 (안전장치)
            df = df.dropna(subset=['start_date'])

            # 만약 데이터가 비어서 컬럼 변환이 안 된 경우 방어
            if 'start_date' in df.columns and 'end_date' in df.columns and not df.empty:
                # 날짜순 정렬
                df = df.sort_values(by='start_date')
                
                for _, row in df.iterrows():
                    d_str = f"{row['start_date']}"
                    # 종료일이 있고 시작일과 다르면 표시
                    if pd.notnull(row['end_date']) and row['start_date'] != row['end_date']:
                        d_str += f" ~ {row['end_date']}"
                        
                    with st.expander(f"[{row['category']}] {d_str} : {row['title']}"):
                        st.write(f"**내용:** {row.get('description', '-')}")
                        st.write(f"**등록자:** {row.get('created_by') or row.get('author') or '-'}")
                        
                        if st.button("삭제", key=f"del_sched_{row['id']}"):
                            db.delete_schedule(row['id'])
                            st.rerun()
            else:
                st.info("표시할 수 있는 유효한 일정이 없습니다.")
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
                    if db.add_contact(comp, name, phone, email, cat, memo, "일반"):
                        st.success("저장되었습니다.")
                        st.session_state['show_contact_form'] = False
                        st.rerun()
                    else:
                        st.error("저장 실패")

        # 연락처 목록
        contacts = db.get_contacts()
        if contacts:
            df_c = pd.DataFrame(contacts)
            
            # DB 컬럼이 tags인데 UI에서 category로 쓰려는 경우 매핑
            if 'tags' in df_c.columns and 'category' not in df_c.columns:
                df_c['category'] = df_c['tags']
                
            # 실제로 존재하는 컬럼만 선택해서 표시 (KeyError 방지)
            cols = ['category', 'company_name', 'manager_name', 'phone', 'email', 'memo']
            if 'person_name' in df_c.columns:
                df_c['manager_name'] = df_c['person_name']
            
            available_cols = [c for c in cols if c in df_c.columns]
            
            st.dataframe(
                df_c[available_cols],
                column_config={
                    "category": "분류", "company_name": "업체명", "manager_name": "담당자",
                    "phone": "전화번호", "email": "이메일", "memo": "비고"
                },
                use_container_width=True
            )
        else:
            st.info("등록된 연락처가 없습니다.")
