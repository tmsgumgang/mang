import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# 캘린더 라이브러리 임포트 (설치 필요: pip install streamlit-calendar)
try:
    from streamlit_calendar import calendar
except ImportError:
    st.error("⚠️ 'streamlit-calendar' 라이브러리가 필요합니다. 터미널에 'pip install streamlit-calendar'를 입력해주세요.")
    calendar = None

def show_collab_ui(db):
    st.markdown("""<style>
        .contact-card { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; margin-bottom: 10px; }
    </style>""", unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 캘린더", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 관리 (캘린더 뷰 적용)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return # 라이브러리 없으면 중단

        c1, c2 = st.columns([3, 1]) # 달력 영역을 넓게 (3:1)
        
        # --- [좌측] 캘린더 시각화 ---
        with c1:
            st.subheader("📆 월간 일정표")
            schedules = db.get_schedules()
            
            calendar_events = []
            
            # 카테고리별 색상 지정
            color_map = {
                "정기점검": "#3b82f6", # 파랑
                "수리/AS": "#ef4444", # 빨강
                "납품/미팅": "#10b981", # 초록
                "회식/기타": "#f59e0b"  # 주황
            }

            if schedules:
                for s in schedules:
                    # DB 시간(UTC) -> ISO 포맷 문자열로 변환 (FullCalendar가 알아서 로컬 시간으로 보여줌)
                    # 데이터프레임 안 거치고 raw dict 사용
                    start_iso = s['start_time']
                    end_iso = s['end_time']
                    
                    calendar_events.append({
                        "title": f"[{s['category']}] {s['title']}",
                        "start": start_iso,
                        "end": end_iso,
                        "backgroundColor": color_map.get(s['category'], "#6b7280"),
                        "borderColor": color_map.get(s['category'], "#6b7280"),
                        "extendedProps": {
                            "id": s['id'],
                            "description": s['description'],
                            "user": s['created_by'],
                            "category": s['category']
                        }
                    })

            # 캘린더 옵션 설정 (월/주/일 보기, 한글화 등)
            calendar_options = {
                "headerToolbar": {
                    "left": "today prev,next",
                    "center": "title",
                    "right": "dayGridMonth,timeGridWeek,timeGridDay"
                },
                "initialView": "dayGridMonth",
                "navLinks": True,
                "selectable": True,
                "editable": False, # 드래그 수정은 DB 연동 복잡해서 일단 끔
            }
            
            # 캘린더 렌더링 & 클릭 이벤트 감지
            cal_state = calendar(events=calendar_events, options=calendar_options, key="my_calendar")

            # [이벤트 클릭 시 상세 정보 표시]
            if cal_state.get("eventClick"):
                event_data = cal_state["eventClick"]["event"]
                props = event_data["extendedProps"]
                
                st.info(f"📌 선택된 일정: **{event_data['title']}**")
                st.write(f"📝 내용: {props['description']}")
                st.caption(f"등록자: {props['user']}")
                
                if st.button("🗑️ 이 일정 삭제", key=f"del_cal_evt_{props['id']}"):
                    db.delete_schedule(props['id'])
                    st.success("삭제되었습니다.")
                    time.sleep(0.5)
                    st.rerun()

        # --- [우측] 일정 등록 폼 ---
        with c2:
            st.markdown("### ➕ 일정 등록")
            with st.form("add_schedule_form_cal"):
                s_title = st.text_input("일정 제목", placeholder="예: 정기 점검")
                s_cat = st.selectbox("분류", ["정기점검", "수리/AS", "납품/미팅", "회식/기타"])
                
                d1, d2 = st.columns(2)
                s_date = d1.date_input("시작 날짜")
                s_time = d2.time_input("시작 시간")
                
                # 종료 시간은 옵션 (여기선 간단히 시작시간 + 1시간으로 자동 설정하거나, 입력 받거나)
                # 복잡도를 줄이기 위해 시작시간만 받아서 저장 (FullCalendar는 end 없으면 1시간으로 간주)
                
                s_desc = st.text_area("상세 내용")
                s_user = st.text_input("등록자", "관리자")
                
                if st.form_submit_button("일정 추가"):
                    # 로컬 시간 -> ISO 포맷
                    local_dt_start = datetime.combine(s_date, s_time)
                    local_dt_end = local_dt_start + timedelta(hours=1) # 기본 1시간
                    
                    if db.add_schedule(s_title, local_dt_start.isoformat(), local_dt_end.isoformat(), s_cat, s_desc, s_user):
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
