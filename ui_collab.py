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
    # [CSS 1] 다크모드 대응 및 고도화된 UI 스타일
    st.markdown("""<style>
        .meta-info { font-size: 0.85rem; color: #888; margin-top: 4px; }
        
        /* 다크모드/라이트모드 자동 대응 카드 */
        .task-card {
            background-color: rgba(128, 128, 128, 0.1); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px; padding: 15px; margin-bottom: 10px;
            color: inherit;
        }
        .task-title { font-size: 1.1rem; font-weight: bold; margin-bottom: 5px; }
        .progress-text { font-size: 0.85rem; font-weight: bold; color: #3b82f6; }
        
        a.custom-phone-btn {
            display: block; width: 100%; background-color: #3b82f6;
            color: white !important; text-decoration: none !important;
            text-align: center; padding: 10px 0; border-radius: 8px;
            font-weight: bold; margin-top: 5px; transition: background 0.3s;
        }
        a.custom-phone-btn:hover { background-color: #2563eb; }
    </style>""", unsafe_allow_html=True)

    # [CSS 2] 캘린더 내부 주입용 CSS (폰트 0.6rem & 제목만 표시)
    calendar_custom_css = """
        .fc-header-toolbar { flex-direction: column !important; gap: 4px !important; margin-bottom: 10px !important; }
        .fc-toolbar-title { font-size: 0.95rem !important; font-weight: bold !important; }
        .fc-button { font-size: 0.65rem !important; padding: 2px 5px !important; }
        .fc-daygrid-day-frame { min-height: 95px !important; }
        
        /* [요청] 일정 폰트 확대 (0.6rem) 및 정보 간소화 */
        .fc-event-title {
            font-size: 0.6rem !important;
            font-weight: 500 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            display: block !important;
        }
        .fc-event-time { display: none !important; } /* 시간 숨김 */
        .fc-event { margin-bottom: 2px !important; border-radius: 4px !important; border: none !important; }
        .fc-col-header-cell-cushion, .fc-daygrid-day-number { font-size: 0.55rem !important; }
    """

    # 탭 구성 (고도화 순서)
    tab1, tab2, tab3 = st.tabs(["📅 일정 & 당직", "🚀 정밀 업무 관리", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직 (기능 복구 완료)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 
        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 스케줄 확인")
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
                    
                    # 캘린더에는 제목만 노출
                    display_title = s['title']
                    if status == '완료': display_title = "✅ " + display_title

                    calendar_events.append({
                        "title": display_title, "start": s['start_time'], "end": s['end_time'],
                        "backgroundColor": bg_color,
                        "extendedProps": {
                            "type": "schedule", "id": str(s['id']), "real_title": s['title'],
                            "category": s.get('category', '기타'), "location": s.get('location', ''),
                            "status": status, "assignee": s.get('assignee', ''), 
                            "description": s.get('description', ''),
                            "sub_tasks": s.get('sub_tasks', [])
                        }
                    })

            if duties:
                for d in duties:
                    calendar_events.append({
                        "title": f"👮‍♂️ {d['worker_name']}", "start": d['date'], "allDay": True,
                        "backgroundColor": "#16a34a", "display": "block", "classNames": ["duty-event"],
                        "extendedProps": { "type": "duty", "id": str(d['id']), "worker_name": d['worker_name'], "date": d['date'] }
                    })

            cal_state = calendar(events=calendar_events, options={
                "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,dayGridWeek,listMonth"},
                "initialView": "dayGridMonth", "locale": "ko", "showNonCurrentDates": False, "fixedWeekCount": False, "dayMaxEvents": 5,
                "displayEventTime": False
            }, custom_css=calendar_custom_css, key="my_calendar_v285")

            if cal_state.get("eventClick"): st.session_state.selected_event = cal_state["eventClick"]["event"]

            # 일정 클릭 시 상세 수정 폼
            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                if props.get("type") == "schedule":
                    st.divider()
                    with st.form(key=f"edit_sch_{props['id']}"):
                        st.info(f"📍 {props.get('location')} | 담당: {props.get('assignee', '미정')}")
                        e_title = st.text_input("업무명", value=props['real_title'])
                        c_a, c_b = st.columns(2)
                        e_status = c_a.selectbox("최종 상태", ["진행중", "완료"], index=0 if props.get('status') == '진행중' else 1)
                        e_assignee = c_b.text_input("담당자 변경", value=props.get('assignee', ''))
                        if st.form_submit_button("상태 저장"):
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), props['category'], props['description'], props['location'], e_status, e_assignee):
                                st.success("변경되었습니다."); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

        with c2:
            st.markdown("### ➕ 일정 등록")
            n_title = st.text_input("제목", key="n_tit")
            n_loc = st.text_input("장소", key="n_loc")
            n_assignee = st.text_input("담당자", key="n_asgn")
            n_date = st.date_input("날짜", key="n_d")
            time_options = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)] 
            n_time_str = st.selectbox("시간", time_options, index=6, key="n_t_sel")
            
            if st.button("업무 추가", type="primary", use_container_width=True):
                if n_title:
                    h, m = map(int, n_time_str.split(':'))
                    start = datetime.combine(n_date, datetime.now().replace(hour=h, minute=m).time())
                    db.add_schedule(n_title, start.isoformat(), (start + timedelta(hours=1)).isoformat(), "기타", "", "관리자", n_loc, n_assignee)
                    st.success("등록됨"); time.sleep(0.5); st.rerun()

            st.divider()
            st.markdown("### 👮‍♂️ 당직 관리")
            # [복구 완료] 엑셀 업로드와 직접 입력 탭
            d_tab1, d_tab2 = st.tabs(["📥 엑셀", "✍️ 직접"])
            with d_tab1:
                uploaded_file = st.file_uploader("엑셀 파일", type=['xlsx'], key="duty_up")
                if uploaded_file and st.button("반영"):
                    df = pd.read_excel(uploaded_file)
                    for _, row in df.iterrows(): db.set_duty_worker(pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d"), str(row.iloc[1]))
                    st.success("반영 완료!"); st.rerun()
            with d_tab2:
                m_date = st.date_input("날짜 선택", key="m_duty_d")
                m_name = st.text_input("근무자 이름", key="m_duty_n")
                if st.button("당직 등록"):
                    if m_name: 
                        db.set_duty_worker(str(m_date), m_name)
                        st.success("등록됨"); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 정밀 업무 관리 (🔥 하위 체크리스트 & 공정률 평가)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("🚀 공정률 관리 대시보드")
        
        # 1. 상단 통계 요약
        stats = db.get_task_stats()
        m1, m2, m3 = st.columns(3)
        m1.metric("전체", f"{stats['total']}건")
        m2.metric("진행 중", f"{stats['pending']}건")
        m3.metric("완료됨", f"{stats['completed']}건")
        
        # 2. 전역 필터 및 완료 업무 보기 설정
        c_f1, c_f2, c_f3 = st.columns([2, 2, 1.5])
        view_all = c_f3.toggle("✅ 완료된 업무 포함", value=False)
        
        all_tasks = db.get_schedules(include_completed=view_all)
        if not all_tasks:
            st.info("관리할 업무가 없습니다.")
        else:
            loc_list = sorted(list(set([t.get('location') or "미지정" for t in all_tasks])))
            user_list = sorted(list(set([t.get('assignee') or "미지정" for t in all_tasks])))
            
            sel_loc = c_f1.multiselect("📍 장소 필터", options=loc_list)
            sel_user = c_f2.multiselect("👤 담당 필터", options=user_list)
            
            filtered_tasks = all_tasks
            if sel_loc: filtered_tasks = [t for t in filtered_tasks if (t.get('location') or "미지정") in sel_loc]
            if sel_user: filtered_tasks = [t for t in filtered_tasks if (t.get('assignee') or "미지정") in sel_user]

            st.divider()

            # 3. 업무 카드 상세 리스트
            for task in filtered_tasks:
                t_id = task['id']
                sub_tasks = task.get('sub_tasks', [])
                
                # 공정률 계산
                total_sub = len(sub_tasks)
                done_sub = len([stk for stk in sub_tasks if stk.get('done')])
                progress = (done_sub / total_sub * 100) if total_sub > 0 else (100 if task['status'] == '완료' else 0)
                
                with st.container():
                    # 카드 헤더
                    col_t1, col_t2 = st.columns([4, 1])
                    with col_t1:
                        st.markdown(f"""
                        <div class="task-card">
                            <div class="task-loc">📍 {task.get('location', '미지정')} | 👤 {task.get('assignee', '미정')}</div>
                            <div class="task-title">{task['title']}</div>
                            <div class="progress-text">현재 공정률: {progress:.1f}%</div>
                        </div>
                        """, unsafe_allow_html=True)
                        st.progress(progress / 100)
                    
                    with col_t2:
                        # 모든 하위 업무가 완료되어야 메인 완료 버튼 활성화
                        is_ready = (progress == 100)
                        if task['status'] == '진행중':
                            if st.button("최종 완료", key=f"comp_{t_id}", disabled=not is_ready, use_container_width=True):
                                db.update_schedule(t_id, task['title'], task['start_time'], task['end_time'], task['category'], task['description'], task['location'], "완료", task['assignee'])
                                st.balloons(); st.rerun()
                            if not is_ready: st.caption("⚠️ 체크리스트 미달성")
                        else:
                            st.success("완료됨")

                    # 4. 하위 체크리스트 관리 (Expander)
                    with st.expander(f"📝 체크리스트 ({done_sub}/{total_sub})"):
                        # 하위 항목 상태 변경 처리
                        new_sub_tasks = []
                        changed = False
                        for idx, stk in enumerate(sub_tasks):
                            cb = st.checkbox(stk['name'], value=stk.get('done', False), key=f"chk_{t_id}_{idx}")
                            if cb != stk.get('done'):
                                stk['done'] = cb
                                changed = True
                            new_sub_tasks.append(stk)
                        
                        # 하위 항목 추가
                        add_col1, add_col2 = st.columns([3, 1])
                        new_item = add_col1.text_input("새 항목 추가", key=f"add_sub_{t_id}", label_visibility="collapsed")
                        if add_col2.button("추가", key=f"add_btn_{t_id}"):
                            if new_item:
                                new_sub_tasks.append({"name": new_item, "done": False})
                                changed = True
                        
                        # 변경사항 DB 즉시 반영
                        if changed:
                            db.update_schedule(t_id, task['title'], task['start_time'], task['end_time'], task['category'], task['description'], task['location'], task['status'], task['assignee'], sub_tasks=new_sub_tasks)
                            st.rerun()

    # ------------------------------------------------------------------
    # [Tab 3] 업체 연락처 (기존 로직 유지)
    # ------------------------------------------------------------------
    with tab3:
        st.subheader("📒 업체 연락처")
        search_txt = st.text_input("🔍 검색 (업체, 담당자, 태그...)", key="con_search")
        if search_txt:
            all_contacts = db.get_contacts()
            filtered = [c for c in all_contacts if search_txt.lower() in f"{c.get('company_name')} {c.get('person_name')} {c.get('tags')}".lower()]
            for c in filtered:
                with st.container(border=True):
                    st.markdown(f"**{c['company_name']}** / 👤 {c['person_name']}")
                    if c.get('phone'):
                        st.markdown(f'<a href="tel:{re.sub(r"[^0-9]", "", str(c["phone"]))}" target="_self" class="custom-phone-btn">📞 {c["phone"]} 전화걸기</a>', unsafe_allow_html=True)
