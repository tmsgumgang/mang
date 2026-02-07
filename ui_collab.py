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
    # [CSS 1] 다크모드 대응 및 직관적인 UI 스타일
    st.markdown("""<style>
        .meta-info { font-size: 0.85rem; color: #888; margin-top: 4px; }
        .task-card {
            background-color: rgba(128, 128, 128, 0.1); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px; padding: 15px; margin-bottom: 10px;
            color: inherit;
        }
        .task-title { font-size: 1.1rem; font-weight: bold; margin-bottom: 5px; }
        .progress-text { font-size: 0.85rem; font-weight: bold; color: #3b82f6; }
        
        /* 상태별 라벨 스타일 */
        .status-badge-pending { color: #f59e0b; font-weight: bold; font-size: 0.8rem; }
        .status-badge-done { color: #10b981; font-weight: bold; font-size: 0.8rem; }

        a.custom-phone-btn {
            display: block; width: 100%; background-color: #3b82f6;
            color: white !important; text-decoration: none !important;
            text-align: center; padding: 10px 0; border-radius: 8px;
            font-weight: bold; margin-top: 5px; transition: background 0.3s;
        }
        a.custom-phone-btn:hover { background-color: #2563eb; }
    </style>""", unsafe_allow_html=True)

    # [CSS 2] 캘린더 내부 주입용 CSS
    calendar_custom_css = """
        .fc-header-toolbar { flex-direction: column !important; gap: 4px !important; margin-bottom: 10px !important; }
        .fc-toolbar-title { font-size: 0.95rem !important; font-weight: bold !important; }
        .fc-button { font-size: 0.65rem !important; padding: 2px 5px !important; }
        .fc-daygrid-day-frame { min-height: 95px !important; }
        .fc-event-title {
            font-size: 0.6rem !important; font-weight: 500 !important;
            line-height: 1.2 !important; white-space: nowrap !important;
            overflow: hidden !important; text-overflow: ellipsis !important;
            display: block !important;
        }
        .fc-event-time { display: none !important; } 
        .fc-event { margin-bottom: 2px !important; border-radius: 4px !important; border: none !important; }
    """

    tab1, tab2, tab3 = st.tabs(["📅 일정 & 당직", "🚀 정밀 업무 관리", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 
        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 스케줄 확인")
            if "selected_event" not in st.session_state: st.session_state.selected_event = None

            schedules = db.get_schedules(include_completed=True)
            duties = db.get_duty_roster()
            calendar_events = []
            
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            for s in schedules:
                status = s.get('status', '진행중')
                bg_color = color_map.get(s.get('category', '기타'), "#6b7280")
                if status == '완료': bg_color = "#9ca3af" 
                
                # [요청 4] 완료 안된 업무는 ⏳ 표시를 추가하여 구분감 강화
                prefix = "✅ " if status == '완료' else "⏳ "
                calendar_events.append({
                    "title": prefix + s['title'],
                    "start": s['start_time'], "end": s['end_time'],
                    "backgroundColor": bg_color,
                    "extendedProps": {
                        "type": "schedule", "id": str(s['id']), "real_title": s['title'],
                        "category": s.get('category', '기타'), "location": s.get('location', ''),
                        "status": status, "assignee": s.get('assignee', ''), 
                        "description": s.get('description', ''), "sub_tasks": s.get('sub_tasks', [])
                    }
                })

            for d in duties:
                calendar_events.append({
                    "title": f"👮‍♂️ {d['worker_name']}", "start": d['date'], "allDay": True,
                    "backgroundColor": "#16a34a", "display": "block",
                    "extendedProps": { "type": "duty", "id": str(d['id']) }
                })

            cal_state = calendar(events=calendar_events, options={
                "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,dayGridWeek,listMonth"},
                "initialView": "dayGridMonth", "locale": "ko", "fixedWeekCount": False, "displayEventTime": False
            }, custom_css=calendar_custom_css, key="my_calendar_v289")

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
                        e_assignee = st.text_input("담당자", value=props.get('assignee', ''))
                        if st.form_submit_button("상태 저장"):
                            db.update_schedule(props['id'], title=e_title, status=e_status, assignee=e_assignee)
                            st.session_state.selected_event = None; st.rerun()

        with c2:
            st.markdown("### ➕ 일정 등록")
            n_title = st.text_input("제목", key="n_tit")
            n_loc = st.text_input("장소", key="n_loc")
            n_assignee = st.text_input("담당자", key="n_asgn")
            n_date = st.date_input("날짜", key="n_d")
            time_options = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)] 
            n_time_str = st.selectbox("시간", time_options, index=6)
            
            if st.button("업무 추가", type="primary", use_container_width=True):
                if n_title:
                    h, m = map(int, n_time_str.split(':'))
                    start = datetime.combine(n_date, datetime.now().replace(hour=h, minute=m).time())
                    res, err = db.add_schedule(
                        title=n_title, start_dt=start.isoformat(), 
                        end_dt=(start + timedelta(hours=1)).isoformat(), 
                        cat="기타", desc="", user="관리자", 
                        location=n_loc, assignee=n_assignee, sub_tasks=[]
                    )
                    if res: st.success("저장됨!"); time.sleep(0.5); st.rerun()
                    else: st.error(f"저장 실패: {err}")

            st.divider()
            st.markdown("### 👮‍♂️ 당직 관리")
            d_tab1, d_tab2 = st.tabs(["📥 엑셀", "✍️ 직접"])
            with d_tab1:
                uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'], key="duty_up")
                if uploaded_file and st.button("반영"):
                    df = pd.read_excel(uploaded_file)
                    for _, row in df.iterrows(): db.set_duty_worker(pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d"), str(row.iloc[1]))
                    st.rerun()
            with d_tab2:
                m_date = st.date_input("날짜", key="m_duty_d")
                m_name = st.text_input("이름", key="m_duty_n")
                if st.button("수동 등록"):
                    if m_name: db.set_duty_worker(str(m_date), m_name); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 정밀 업무 관리 (체크리스트 & 완료 취소 & 세부 수정)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("🚀 공정률 관리 대시보드")
        stats = db.get_task_stats()
        m1, m2, m3 = st.columns(3)
        m1.metric("전체", f"{stats['total']}건")
        m2.metric("진행 중", f"{stats['pending']}건")
        m3.metric("완료됨", f"{stats['completed']}건")
        
        c_f1, c_f2, c_f3 = st.columns([2, 2, 1.5])
        view_all = c_f3.toggle("✅ 완료된 업무도 보기", value=False)
        all_tasks = db.get_schedules(include_completed=view_all)
        
        if not all_tasks:
            st.info("조회할 업무가 없습니다.")
        else:
            loc_list = sorted(list(set([t.get('location') or "미지정" for t in all_tasks])))
            user_list = sorted(list(set([t.get('assignee') or "미지정" for t in all_tasks])))
            sel_loc = c_f1.multiselect("📍 장소 필터", options=loc_list)
            sel_user = c_f2.multiselect("👤 담당 필터", options=user_list)
            
            filtered = [t for t in all_tasks if (not sel_loc or t.get('location') in sel_loc) and (not sel_user or t.get('assignee') in sel_user)]

            for task in filtered:
                t_id = task['id']
                sub_tasks = task.get('sub_tasks', [])
                total_sub = len(sub_tasks)
                done_sub = len([stk for stk in sub_tasks if stk.get('done')])
                progress = (done_sub / total_sub * 100) if total_sub > 0 else (100 if task['status'] == '완료' else 0)

                with st.container():
                    col_t1, col_t2 = st.columns([4, 1.2])
                    with col_t1:
                        status_label = "✅ 완료됨" if task['status'] == '완료' else "⏳ 진행중"
                        st.markdown(f"""
                        <div class="task-card">
                            <div class="task-loc">📍 {task.get('location', '미정')} | 👤 {task.get('assignee', '미정')} | {status_label}</div>
                            <div class="task-title">{task['title']}</div>
                            <div class="progress-text">달성도: {progress:.1f}% ({done_sub}/{total_sub})</div>
                        </div>
                        """, unsafe_allow_html=True)
                        st.progress(progress / 100)
                    
                    with col_t2:
                        # [요청 2] 완료 취소 기능 추가
                        if task['status'] == '완료':
                            if st.button("⏪ 진행 복구", key=f"rev_{t_id}", use_container_width=True):
                                db.update_schedule(t_id, status="진행중")
                                st.rerun()
                        else:
                            is_ready = (progress == 100)
                            if st.button("최종 완료", key=f"comp_{t_id}", disabled=not is_ready, use_container_width=True, type="primary"):
                                db.update_schedule(t_id, status="완료")
                                st.balloons(); st.rerun()
                            if not is_ready: st.caption("❌ 체크리스트 미달성")

                    # [요청 3, 5, 6] 체크리스트 관리 및 업무 세부 수정 기능 통합
                    exp_label = f"🛠️ 관리 및 체크리스트 ({done_sub}/{total_sub})"
                    with st.expander(exp_label):
                        # 6. 업무 세부 내용 수정 폼
                        st.markdown("##### ✏️ 업무 정보 수정")
                        with st.form(key=f"edit_detail_{t_id}"):
                            u_col1, u_col2 = st.columns(2)
                            u_title = u_col1.text_input("제목", value=task['title'])
                            u_loc = u_col2.text_input("장소", value=task.get('location', ''))
                            u_asgn = st.text_input("담당자", value=task.get('assignee', ''))
                            if st.form_submit_button("정보 업데이트"):
                                db.update_schedule(t_id, title=u_title, location=u_loc, assignee=u_asgn)
                                st.rerun()
                        
                        st.divider()
                        st.markdown("##### 📝 체크리스트 항목")
                        # 체크리스트 상태 변경
                        new_sub_tasks = []
                        changed = False
                        for idx, stk in enumerate(sub_tasks):
                            c_cb = st.checkbox(stk['name'], value=stk.get('done', False), key=f"chk_{t_id}_{idx}")
                            if c_cb != stk.get('done'):
                                stk['done'] = c_cb
                                changed = True
                            new_sub_tasks.append(stk)
                        
                        # [요청 5] 체크리스트 추가 시 깜빡임 개선을 위한 폼 사용
                        with st.form(key=f"add_sub_form_{t_id}", clear_on_submit=True):
                            ac1, ac2 = st.columns([3, 1])
                            new_item_name = ac1.text_input("새 하위 업무 입력", placeholder="예: 시약 보충")
                            if ac2.form_submit_button("추가"):
                                if new_item_name:
                                    new_sub_tasks.append({"name": new_item_name, "done": False})
                                    changed = True
                        
                        if changed:
                            db.update_schedule(t_id, sub_tasks=new_sub_tasks)
                            st.rerun()

    # [Tab 3] 업체 연락처 (기존 유지)
    with tab3:
        st.subheader("📒 업체 연락처")
        search_txt = st.text_input("🔍 검색 (업체, 담당자, 태그...)", key="con_search")
        if search_txt:
            all_contacts = db.get_contacts()
            filtered = [c for c in all_contacts if search_txt.lower() in f"{c.get('company_name')} {c.get('person_name')} {c.get('tags')}".lower()]
            for c in filtered:
                with st.container(border=True):
                    st.markdown(f"**{c['company_name']}** / 👤 {c.get('person_name')}")
                    if c.get('phone'):
                        st.markdown(f'<a href="tel:{re.sub(r"[^0-9]", "", str(c["phone"]))}" target="_self" class="custom-phone-btn">📞 {c["phone"]} 전화걸기</a>', unsafe_allow_html=True)
