import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# 캘린더 라이브러리 임포트
try:
    from streamlit_calendar import calendar
except ImportError:
    st.error("⚠️ 'streamlit-calendar' 라이브러리가 필요합니다.")
    calendar = None

def show_collab_ui(db):
    st.markdown("""<style>
        .contact-card { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; margin-bottom: 10px; }
        .schedule-row { padding: 10px; border-bottom: 1px solid #eee; }
    </style>""", unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 캘린더", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 관리 (V257 Upgraded)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 

        c1, c2 = st.columns([3, 1]) 
        
        # --- [좌측] 캘린더 시각화 ---
        with c1:
            st.subheader("📆 월간 일정표")
            schedules = db.get_schedules()
            
            calendar_events = []
            
            # [V257] 카테고리별 색상 업데이트
            color_map = {
                "점검": "#3b82f6",  # 파랑
                "월간": "#8b5cf6",  # 보라
                "회의": "#10b981",  # 초록
                "행사": "#f59e0b",  # 주황
                "기타": "#6b7280"   # 회색
            }

            if schedules:
                for s in schedules:
                    # DB 시간(UTC) -> ISO 포맷
                    start_iso = s['start_time']
                    end_iso = s['end_time']
                    cat = s.get('category', '기타')
                    loc = s.get('location', '') # 장소 정보
                    
                    # 제목에 장소 있으면 표시 (예: [회의] 주간회의 @대회의실)
                    display_title = f"[{cat}] {s['title']}"
                    if loc: display_title += f" (@{loc})"

                    calendar_events.append({
                        "title": display_title,
                        "start": start_iso,
                        "end": end_iso,
                        "backgroundColor": color_map.get(cat, "#6b7280"), # 없으면 회색
                        "borderColor": color_map.get(cat, "#6b7280"),
                        "extendedProps": {
                            "id": s['id'],
                            "description": s.get('description', ''),
                            "user": s.get('created_by', ''),
                            "category": cat,
                            "location": loc
                        }
                    })

            # 캘린더 옵션
            calendar_options = {
                "headerToolbar": {
                    "left": "today prev,next",
                    "center": "title",
                    "right": "dayGridMonth,timeGridWeek,listMonth"
                },
                "initialView": "dayGridMonth",
                "navLinks": True,
                "selectable": True,
                "editable": False,
            }
            
            cal_state = calendar(events=calendar_events, options=calendar_options, key="my_calendar")

            # [이벤트 클릭 시 상세 정보]
            if cal_state.get("eventClick"):
                event_data = cal_state["eventClick"]["event"]
                props = event_data["extendedProps"]
                
                st.info(f"📌 **{event_data['title']}**")
                
                # 상세 내용 표시
                if props.get('location'):
                    st.write(f"📍 **장소:** {props['location']}")
                
                st.write(f"📝 **내용:** {props['description']}")
                st.caption(f"등록자: {props['user']} | 분류: {props['category']}")
                
                if st.button("🗑️ 이 일정 삭제", key=f"del_cal_evt_{props['id']}"):
                    db.delete_schedule(props['id'])
                    st.success("삭제되었습니다.")
                    time.sleep(0.5)
                    st.rerun()

        # --- [우측] 일정 등록 폼 (V257 수정됨) ---
        with c2:
            st.markdown("### ➕ 일정 등록")
            with st.form("add_schedule_form_cal"):
                # 1. 제목
                s_title = st.text_input("일정 제목", placeholder="예: 정기 점검")
                
                # 2. [V257] 분류 (직접입력 로직 추가)
                cat_options = ["점검", "월간", "회의", "행사", "기타", "직접입력"]
                s_cat_select = st.selectbox("분류", cat_options)
                
                if s_cat_select == "직접입력":
                    s_cat = st.text_input("분류 입력", placeholder="예: 긴급")
                else:
                    s_cat = s_cat_select

                # 3. [V257] 장소 추가
                s_loc = st.text_input("장소 (선택)", placeholder="예: 3층 회의실")

                st.markdown("---")
                # 4. 날짜 및 시간 (시작)
                d1, t1 = st.columns(2)
                s_date = d1.date_input("시작 날짜")
                s_time = t1.time_input("시작 시간")
                
                # 5. [V257] 종료 시간 (선택)
                use_end_time = st.checkbox("종료 시간 설정")
                e_date = s_date # 기본값
                e_time = s_time # 기본값
                
                if use_end_time:
                    d2, t2 = st.columns(2)
                    e_date = d2.date_input("종료 날짜", value=s_date)
                    e_time = t2.time_input("종료 시간", value=(datetime.combine(s_date, s_time) + timedelta(hours=1)).time())
                
                s_desc = st.text_area("상세 내용")
                s_user = st.text_input("등록자", "관리자")
                
                if st.form_submit_button("일정 추가"):
                    if not s_title:
                        st.error("제목을 입력해주세요.")
                    else:
                        # 시작 시간 (Local)
                        local_dt_start = datetime.combine(s_date, s_time)
                        
                        # 종료 시간 계산
                        if use_end_time:
                            local_dt_end = datetime.combine(e_date, e_time)
                        else:
                            # 종료 시간 없으면 기본 1시간으로 설정 (달력 가시성 확보)
                            local_dt_end = local_dt_start + timedelta(hours=1)
                        
                        # 분류 값 최종 확인
                        final_cat = s_cat if s_cat else "기타"

                        # DB 저장 (ISO 포맷)
                        if db.add_schedule(s_title, local_dt_start.isoformat(), local_dt_end.isoformat(), final_cat, s_desc, s_user, s_loc):
                            st.success("등록 완료!")
                            time.sleep(0.5)
                            st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리 (기존 유지)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("📒 주요 업체 및 담당자 연락처")
        
        search_txt = st.text_input("🔍 연락처 검색 (업체명, 담당자, 태그)", placeholder="예: 시마즈, 펌프")
        
        all_contacts = db.get_contacts()
        filtered = []
        if search_txt:
            search_txt = search_txt.lower()
            for c in all_contacts:
                c_name = c.get('company_name') or ""
                p_name = c.get('person_name') or ""
                tags = c.get('tags') or ""
                raw = f"{c_name} {p_name} {tags}".lower()
                if search_txt in raw:
                    filtered.append(c)
        else:
            filtered = all_contacts

        if filtered:
            df_con = pd.DataFrame(filtered)
            target_cols = ['id', 'company_name', 'person_name', 'phone', 'email', 'tags', 'memo']
            valid_cols = [col for col in target_cols if col in df_con.columns]
            display_df = df_con[valid_cols].copy()
            col_map = {'id': 'ID', 'company_name': '업체명', 'person_name': '담당자', 'phone': '전화번호', 'email': '이메일', 'tags': '태그', 'memo': '메모'}
            display_df.rename(columns=col_map, inplace=True)
            
            edited_df = st.data_editor(display_df, key="contact_editor", num_rows="dynamic", use_container_width=True, hide_index=True, disabled=["ID"])
            
            if st.button("💾 변경사항 저장 (새로고침)"):
                st.toast("데이터가 갱신되었습니다.")
                st.rerun()
        else:
            st.info("연락처 데이터가 없습니다.")

        st.divider()
        
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
