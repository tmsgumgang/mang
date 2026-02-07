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
    # [CSS 1] 다크모드 대응 및 고도화된 업무 카드 스타일
    st.markdown("""<style>
        .meta-info { font-size: 0.85rem; color: #888; margin-top: 4px; }
        
        /* [V284] 다크모드/라이트모드 자동 대응 카드 배경 */
        .task-card {
            background-color: rgba(128, 128, 128, 0.1); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px; 
            padding: 15px; 
            margin-bottom: 10px;
            color: inherit; /* 시스템 폰트 색상 따라감 */
        }
        
        .task-title { font-size: 1rem; font-weight: bold; margin-bottom: 3px; }
        .task-loc { font-size: 0.85rem; color: #3b82f6; font-weight: 600; }

        a.custom-phone-btn {
            display: block; width: 100%; background-color: #3b82f6;
            color: white !important; text-decoration: none !important;
            text-align: center; padding: 10px 0; border-radius: 8px;
            font-weight: bold; margin-top: 5px; transition: background 0.3s;
        }
        a.custom-phone-btn:hover { background-color: #2563eb; }
    </style>""", unsafe_allow_html=True)

    # [CSS 2] 캘린더 내부 주입용 CSS (V284: 폰트 확대 및 정보 간소화)
    calendar_custom_css = """
        .fc-header-toolbar { flex-direction: column !important; gap: 4px !important; margin-bottom: 5px !important; }
        .fc-toolbar-title { font-size: 0.95rem !important; font-weight: bold !important; }
        .fc-button { font-size: 0.65rem !important; padding: 2px 5px !important; }
        .fc-daygrid-day-frame { min-height: 95px !important; }
        
        /* [요청 1] 일정 폰트 크기 확대 (0.6rem) */
        .fc-event-title {
            font-size: 0.6rem !important;
            font-weight: 500 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            display: block !important;
        }
        
        /* [요청 2] 캘린더 화면에서 시간 숫자/담당자 숨기기 */
        .fc-event-time { display: none !important; }
        
        .fc-event {
            margin-bottom: 2px !important;
            padding: 1px 2px !important;
            border-radius: 4px !important;
            border: none !important;
        }
        .fc-col-header-cell-cushion, .fc-daygrid-day-number { font-size: 0.5rem !important; }
    """

    # 탭 구성 (V284 순서 유지)
    tab1, tab2, tab3 = st.tabs(["📅 일정 & 당직", "🚀 업무 관리 대시보드", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 
        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 월간/주간 스케줄")
            if "selected_event" not in st.session_state: st.session_state.selected_event = None

            schedules = db.get_schedules()
            duties = db.get_duty_roster()
            calendar_events = []
            
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            if schedules:
                for s in schedules:
                    status = s.get('status', '진행중')
                    bg_color = color_map.get(s.get('category', '기타'), "#6b7280")
                    if status == '완료': bg_color = "#9ca3af" 
                    
                    # [요청 2] 일정 시간/담당자 빼고 '제목'만 표시
                    display_title = s['title']
                    if status == '완료': display_title = "✅ " + display_title

                    calendar_events.append({
                        "title": display_title,
                        "start": s['start_time'], "end": s['end_time'],
                        "backgroundColor": bg_color, "borderColor": bg_color,
                        "extendedProps": {
                            "type": "schedule", "id": str(s['id']), "real_title": s['title'],
                            "category": s.get('category', '기타'), "location": s.get('location', ''),
                            "status": status, "assignee": s.get('assignee', ''), "description": s.get('description', '')
                        }
                    })

            if duties:
                for d in duties:
                    calendar_events.append({
                        "title": f"👮‍♂️ {d['worker_name']}", "start": d['date'], "allDay": True,
                        "backgroundColor": "#16a34a", "borderColor": "#16a34a", "display": "block",
                        "extendedProps": { "type": "duty", "id": str(d['id']), "worker_name": d['worker_name'], "date": d['date'] }
                    })

            cal_state = calendar(
                events=calendar_events, 
                options={
                    "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,dayGridWeek,listMonth"},
                    "initialView": "dayGridMonth", "locale": "ko", "showNonCurrentDates": False, "fixedWeekCount": False, "dayMaxEvents": 5,
                    "displayEventTime": False # 시간 표시 원천 차단
                }, 
                custom_css=calendar_custom_css, 
                key="my_calendar_v284"
            )

            if cal_state.get("eventClick"): st.session_state.selected_event = cal_state["eventClick"]["event"]

            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                if props.get("type") == "schedule":
                    st.divider()
                    with st.form(key=f"edit_sch_{props['id']}"):
                        st.info(f"🔍 **업무 상세** (담당: {props.get('assignee', '미정')})")
                        e_title = st.text_input("제목", value=props['real_title'])
                        c_a, c_b = st.columns(2)
                        e_status = c_a.selectbox("상태", ["진행중", "완료"], index=0 if props.get('status') == '진행중' else 1)
                        e_assignee = c_b.text_input("담당자", value=props.get('assignee', ''))
                        if st.form_submit_button("변경 사항 저장"):
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), props['category'], props['description'], props['location'], e_status, e_assignee):
                                st.success("반영되었습니다."); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

        with c2:
            st.markdown("### ➕ 일정 등록")
            n_title = st.text_input("제목", key="n_tit")
            c_l, c_as = st.columns(2)
            n_loc = c_l.text_input("장소", key="n_loc")
            n_assignee = c_as.text_input("담당자", key="n_asgn")
            nd1, nt1 = st.columns(2)
            n_date = nd1.date_input("날짜", key="n_d")
            time_options = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)] 
            n_time_str = nt1.selectbox("시간", time_options, index=6, key="n_t_sel")
            
            if st.button("저장", type="primary", use_container_width=True):
                if n_title:
                    h, m = map(int, n_time_str.split(':'))
                    start = datetime.combine(n_date, datetime.now().replace(hour=h, minute=m).time())
                    db.add_schedule(n_title, start.isoformat(), (start + timedelta(hours=1)).isoformat(), "기타", "", "관리자", n_loc, n_assignee)
                    st.success("등록됨"); time.sleep(0.5); st.rerun()

            st.divider()
            st.markdown("### 👮‍♂️ 당직 관리")
            uploaded_file = st.file_uploader("엑셀 반영", type=['xlsx'], key="duty_up")
            if uploaded_file and st.button("반영하기"):
                df = pd.read_excel(uploaded_file)
                for _, row in df.iterrows(): db.set_duty_worker(pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d"), str(row.iloc[1]))
                st.success("완료!"); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 업무 관리 대시보드 (🔥 고도화 버전)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("🚀 업무 추진 대시보드")
        
        # [데이터 수신] 통계 정보 (V284 db_services 필요)
        stats = db.get_task_stats()
        
        # 1. 지표(Metrics) 상단 배치
        m1, m2, m3 = st.columns(3)
        m1.metric("전체 공정", f"{stats['total']}건")
        m2.metric("진행 중", f"{stats['pending']}건", delta_color="inverse")
        m3.metric("완료됨", f"{stats['completed']}건")
        
        # 2. 진행률 바
        progress = (stats['completed'] / stats['total']) if stats['total'] > 0 else 0
        st.write(f"**실시간 전체 공정률: {progress*100:.1f}%**")
        st.progress(progress)
        
        st.divider()

        # 3. 고도화 필터링
        all_pending = db.get_pending_schedules()
        if not all_pending:
            st.success("🎉 모든 업무가 완료된 상태입니다!")
        else:
            st.markdown("#### 🔍 리스트 필터링")
            f1, f2 = st.columns(2)
            loc_opts = sorted(list(set([t.get('location') or "미지정" for t in all_pending])))
            asgn_opts = sorted(list(set([t.get('assignee') or "미지정" for t in all_pending])))
            
            sel_loc = f1.multiselect("📍 장소 필터", options=loc_opts)
            sel_asgn = f2.multiselect("👤 담당자 필터", options=asgn_opts)
            
            display_tasks = all_pending
            if sel_loc: display_tasks = [t for t in display_tasks if (t.get('location') or "미지정") in sel_loc]
            if sel_asgn: display_tasks = [t for t in display_tasks if (t.get('assignee') or "미지정") in sel_asgn]

            # 4. 업무 카드 리스트 (다크모드 대응 스타일 적용)
            for task in display_tasks:
                with st.container():
                    st.markdown(f"""
                    <div class="task-card">
                        <div class="task-loc">📍 {task.get('location', '위치미정')}</div>
                        <div class="task-title">{task['title']}</div>
                        <div class="meta-info">📅 기한: {task['start_time'][:10]} | 👤 담당: {task.get('assignee', '미정')}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"✅ 업무 완료하기", key=f"dash_done_{task['id']}", use_container_width=True):
                        db.update_schedule(task['id'], task['title'], task['start_time'], task.get('end_time'), task.get('category'), "", task.get('location'), "완료", task.get('assignee'))
                        st.balloons(); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 3] 업체 연락처
    # ------------------------------------------------------------------
    with tab3:
        st.subheader("📒 업체 연락처")
        search_txt = st.text_input("🔍 업체, 담당자, 태그 검색", placeholder="검색어를 입력하세요.")
        if search_txt:
            all_contacts = db.get_contacts()
            filtered = [c for c in all_contacts if search_txt.lower() in f"{c.get('company_name')} {c.get('person_name')} {c.get('tags')}".lower()]
            for c in filtered:
                with st.container(border=True):
                    st.markdown(f"**{c['company_name']}** / 👤 {c['person_name']}")
                    if c.get('phone'):
                        st.markdown(f'<a href="tel:{re.sub(r"[^0-9]", "", str(c["phone"]))}" target="_self" class="custom-phone-btn">📞 {c["phone"]} 전화걸기</a>', unsafe_allow_html=True)
