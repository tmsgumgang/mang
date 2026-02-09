import streamlit as st
import pandas as pd
import time
import re
from datetime import datetime, timedelta, timezone

# 캘린더 라이브러리 임포트
try:
    from streamlit_calendar import calendar
except ImportError:
    st.error("⚠️ 'streamlit-calendar' 라이브러리가 필요합니다.")
    calendar = None

def show_collab_ui(db):
    # [CSS 1] 다크모드 대응 및 모바일 최적화 스타일
    st.markdown("""<style>
        .task-card {
            background-color: rgba(128, 128, 128, 0.1); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px; padding: 12px; margin-bottom: 8px; color: inherit;
        }
        .contact-memo { font-size: 0.8rem; color: #aaa; font-style: italic; margin-top: 5px; border-left: 2px solid #3b82f6; padding-left: 5px; }
        a.custom-phone-btn { display: block; width: 100%; background-color: #3b82f6; color: white !important; text-decoration: none !important; text-align: center; padding: 8px 0; border-radius: 8px; margin-top: 5px; }
    </style>""", unsafe_allow_html=True)

    # [CSS 2] 캘린더 커스텀 (글자 크기 등)
    calendar_custom_css = """
        .fc-toolbar-title { font-size: 1rem !important; }
        .fc-event-title { font-size: 0.75rem !important; white-space: nowrap !important; overflow: hidden !important; }
        .fc-daygrid-day-frame { min-height: 80px !important; }
    """

    if "expanded_task_id" not in st.session_state: st.session_state.expanded_task_id = None

    tab1, tab2, tab3 = st.tabs(["📅 일정 & 당직", "🚀 정밀 업무 관리", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직 (캘린더 시각화 복구)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 
        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 스케줄 확인")
            if "selected_event" not in st.session_state: st.session_state.selected_event = None

            # 데이터 로드
            schedules = db.get_schedules(include_completed=True)
            duties = db.get_duty_roster()
            calendar_events = []
            
            # (1) 스케줄 이벤트 변환
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            if schedules:
                for s in schedules:
                    # [Safety] 날짜 유효성 검사 (ValueError 방지)
                    try:
                        # start_time이 비어있거나 이상하면 건너뜀
                        if not s.get('start_time'): continue
                        pd.to_datetime(s['start_time']) # 테스트 파싱
                    except: continue

                    status = s.get('status', '진행중')
                    bg_color = color_map.get(s.get('category', '기타'), "#6b7280")
                    if status == '완료': bg_color = "#9ca3af" 
                    
                    prefix = "✅ " if status == '완료' else "⏳ "
                    calendar_events.append({
                        "title": prefix + s['title'],
                        "start": s['start_time'], "end": s['end_time'],
                        "backgroundColor": bg_color,
                        "extendedProps": {
                            "type": "schedule", "id": str(s['id']), "real_title": s['title'],
                            "category": s.get('category', '기타'), "location": s.get('location', ''),
                            "status": status, "assignee": s.get('assignee', '')
                        }
                    })

            # (2) 당직(Duty) 이벤트 변환
            for d in duties:
                calendar_events.append({
                    "title": f"👮‍♂️ {d['worker_name']}", "start": d['date'], "allDay": True,
                    "backgroundColor": "#16a34a", "display": "block",
                    "extendedProps": { "type": "duty", "id": str(d['id']) }
                })

            # 캘린더 그리기
            cal_state = calendar(events=calendar_events, options={
                "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,listMonth"},
                "initialView": "dayGridMonth", "locale": "ko", "fixedWeekCount": False, "displayEventTime": False
            }, custom_css=calendar_custom_css, key="my_calendar_v300")

            # 이벤트 클릭 시 수정 폼
            if cal_state.get("eventClick"): st.session_state.selected_event = cal_state["eventClick"]["event"]

            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                if props.get("type") == "schedule":
                    st.divider()
                    with st.form(key=f"edit_sch_cal_{props['id']}"):
                        st.info(f"📍 {props.get('location')} | 담당: {props.get('assignee', '미정')}")
                        e_title = st.text_input("업무명", value=props['real_title'])
                        e_status = st.selectbox("상태", ["진행중", "완료"], index=0 if props['status'] == '진행중' else 1)
                        if st.form_submit_button("상태 저장"):
                            db.update_schedule(props['id'], title=e_title, status=e_status)
                            st.session_state.selected_event = None; st.rerun()

        with c2:
            st.markdown("### ➕ 일정 등록")
            n_title = st.text_input("제목", key="n_tit")
            n_loc = st.text_input("장소", key="n_loc")
            n_assignee = st.text_input("담당자", key="n_asgn")
            n_date = st.date_input("날짜", key="n_d", value=date.today())
            time_options = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)] 
            n_time_str = st.selectbox("시간", time_options, index=6)
            
            if st.button("업무 추가", type="primary", use_container_width=True):
                if n_title:
                    h, m = map(int, n_time_str.split(':'))
                    start = datetime.combine(n_date, datetime.now().replace(hour=h, minute=m).time())
                    # 인자 개수 맞춤
                    res = db.add_schedule(title=n_title, start_dt=start.isoformat(), end_dt=(start + timedelta(hours=1)).isoformat(), cat="기타", desc="", user="관리자", location=n_loc, assignee=n_assignee, sub_tasks=[])
                    if res: st.success("저장됨!"); time.sleep(0.5); st.rerun()
                    else: st.error("실패")

            st.divider()
            st.markdown("### 👮‍♂️ 당직 등록")
            m_date = st.date_input("당직 날짜", key="m_duty_d", value=date.today())
            m_name = st.text_input("당직자 이름", key="m_duty_n")
            if st.button("당직 저장", use_container_width=True):
                if m_name: db.set_duty_worker(str(m_date), m_name); st.success("저장됨"); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 정밀 업무 관리
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("🚀 공정률 관리")
        view_all = st.checkbox("완료된 업무 포함 보기", value=False)
        all_tasks = db.get_schedules(include_completed=view_all)
        
        if all_tasks:
            # [Fix] ValueError 방지 로직 적용
            df = pd.DataFrame(all_tasks)
            if 'start_time' in df.columns:
                df['start_date'] = pd.to_datetime(df['start_time'], errors='coerce').dt.date
            else:
                df['start_date'] = None
            
            # NaT 제거
            df = df.dropna(subset=['start_date']).sort_values('start_date')
            
            for _, row in df.iterrows():
                with st.expander(f"{row['start_date']} : {row['title']} ({row.get('status','-')})"):
                    st.write(f"담당: {row.get('assignee','-')} | 장소: {row.get('location','-')}")
                    if st.button("삭제", key=f"del_t_{row['id']}"):
                        db.delete_schedule(row['id']); st.rerun()
        else:
            st.info("표시할 업무가 없습니다.")

    # ------------------------------------------------------------------
    # [Tab 3] 업체 연락처
    # ------------------------------------------------------------------
    with tab3:
        st.subheader("📒 업체 연락처 관리")
        with st.expander("➕ 새 연락처 등록"):
            with st.form("add_contact_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                comp = c1.text_input("업체명")
                name = c2.text_input("담당자명")
                phone = c1.text_input("전화번호")
                cat = c2.selectbox("분류", ["제조사", "시약", "공사", "기타"])
                memo = st.text_area("메모")
                if st.form_submit_button("저장"):
                    if db.add_contact(comp, name, phone, "", cat, memo, "일반"):
                        st.success("저장 완료"); st.rerun()

        search = st.text_input("🔍 검색", placeholder="업체명, 담당자...")
        contacts = db.get_contacts()
        
        if contacts:
            for c in contacts:
                if search and search not in str(c.values()): continue
                with st.container(border=True):
                    l, r = st.columns([4, 1])
                    with l:
                        st.markdown(f"**{c['company_name']}** ({c.get('person_name','')})")
                        if c.get('phone'): st.markdown(f"📞 {c['phone']}")
                        if c.get('memo'): st.caption(c['memo'])
                    with r:
                        if st.button("🗑️", key=f"del_c_{c['id']}"):
                            db.delete_contact(c['id']); st.rerun()
