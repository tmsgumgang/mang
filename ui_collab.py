import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

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
                
                # [Fix 1] DB의 시간(UTC)을 Pandas Timestamp(UTC)로 명확히 변환
                df['start_time'] = pd.to_datetime(df['start_time'], utc=True)
                
                # [Fix 2] 현재 시간도 UTC 기준으로 가져와서 비교 (에러 해결 핵심)
                now_utc = datetime.now(timezone.utc)
                
                # 어제 이후의 일정만 필터링 (최근 일정 보기)
                upcoming = df[df['start_time'] >= now_utc - timedelta(days=1)]
                
                if not upcoming.empty:
                    # 날짜순 정렬
                    upcoming = upcoming.sort_values(by='start_time')
                    
                    for _, row in upcoming.iterrows():
                        # [Display] 한국 시간(KST)으로 변환해서 보여주기
                        try:
                            kst_time = row['start_time'].tz_convert('Asia/Seoul')
                        except:
                            # 변환 실패시(라이브러리 부재 등) 9시간 수동 더하기 or 그대로 표시
                            kst_time = row['start_time'] + timedelta(hours=9)
                            
                        time_str = kst_time.strftime('%m-%d %H:%M')
                        
                        with st.expander(f"[{row['category']}] {time_str} : {row['title']}"):
                            st.write(f"📝 내용: {row['description']}")
                            st.caption(f"등록자: {row['created_by']}")
                            
                            # 삭제 버튼
                            if st.button("삭제", key=f"del_sch_{row['id']}"):
                                db.delete_schedule(row['id'])
                                st.rerun()
                else:
                    st.info("예정된 일정이 없습니다.")
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
                    # 1. 사용자가 입력한 시간을 합침 (Local Time)
                    local_dt = datetime.combine(s_date, s_time)
                    
                    # 2. DB에는 ISO 포맷 문자열로 저장 (타임존 정보 없이 보내면 보통 UTC나 그대로 저장됨)
                    # 여기서는 심플하게 ISO 포맷 문자열로 변환하여 전송
                    if db.add_schedule(s_title, local_dt.isoformat(), local_dt.isoformat(), s_cat, s_desc, s_user):
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
                # None 데이터 방지
                c_name = c.get('company_name') or ""
                p_name = c.get('person_name') or ""
                tags = c.get('tags') or ""
                
                raw = f"{c_name} {p_name} {tags}".lower()
                if search_txt in raw:
                    filtered.append(c)
        else:
            filtered = all_contacts

        # 연락처 리스트 (데이터 에디터 사용)
        if filtered:
            df_con = pd.DataFrame(filtered)
            
            # 에러 방지: 필요한 컬럼만 추출
            target_cols = ['id', 'company_name', 'person_name', 'phone', 'email', 'tags', 'memo']
            # 실제 존재하는 컬럼만 필터링
            valid_cols = [col for col in target_cols if col in df_con.columns]
            
            display_df = df_con[valid_cols].copy()
            
            # 컬럼명 한글 변환
            col_map = {
                'id': 'ID', 'company_name': '업체명', 'person_name': '담당자',
                'phone': '전화번호', 'email': '이메일', 'tags': '태그', 'memo': '메모'
            }
            display_df.rename(columns=col_map, inplace=True)
            
            edited_df = st.data_editor(
                display_df, 
                key="contact_editor",
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                disabled=["ID"] # ID는 수정 불가
            )
            
            # 수정 사항 감지 및 DB 업데이트 (단순 새로고침용)
            if st.button("💾 변경사항 저장 (새로고침)"):
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
