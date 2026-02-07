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
    # [CSS 1] 메인 화면 및 업무 관리 카드 스타일
    st.markdown("""<style>
        .meta-info { font-size: 0.85rem; color: gray; margin-top: 4px; }
        a.custom-phone-btn {
            display: block; width: 100%; background-color: #3b82f6;
            color: white !important; text-decoration: none !important;
            text-align: center; padding: 8px 0; border-radius: 8px;
            font-weight: bold; margin-top: 5px; transition: background 0.3s;
        }
        a.custom-phone-btn:hover { background-color: #2563eb; }
        
        /* 업무 관리 탭 전용 카드 스타일 */
        .task-card {
            background-color: #f8fafc; border: 1px solid #e2e8f0;
            border-radius: 10px; padding: 12px; margin-bottom: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
    </style>""", unsafe_allow_html=True)

    # [CSS 2] 캘린더 내부 주입용 CSS (모바일 일정 뚫고나옴 방지 핵심)
    calendar_custom_css = """
        .fc-header-toolbar { flex-direction: column !important; gap: 2px !important; margin-bottom: 5px !important; }
        .fc-toolbar-title { font-size: 0.85rem !important; }
        .fc-button { font-size: 0.55rem !important; padding: 1px 4px !important; }
        .fc-daygrid-day-frame { min-height: 85px !important; }
        
        /* [Fix] 날짜 폰트 축소 */
        .fc-col-header-cell-cushion, .fc-daygrid-day-number { font-size: 0.45rem !important; padding: 1px !important; }
        
        /* [Fix] 시간 숫자 대폭 축소 (0.35rem) */
        .fc-event-time {
            font-size: 0.35rem !important; 
            font-weight: normal !important;
            margin-right: 1px !important;
            display: inline-block !important;
        }
        
        /* [Fix] 제목 넘침 방지 및 폰트 축소 */
        .fc-event-title {
            font-size: 0.4rem !important;
            font-weight: normal !important;
            line-height: 1.0 !important;
            white-space: nowrap !important;      /* 줄바꿈 절대 금지 */
            overflow: hidden !important;         /* 넘치는 글자 숨김 */
            text-overflow: ellipsis !important;  /* 끝에 ... 표시 */
            display: inline !important;          /* 시간과 한 줄에 배치 */
        }

        .fc-event-main { padding: 0px 1px !important; overflow: hidden !important; }
        .duty-event .fc-event-main { padding: 0px 1px !important; line-height: 1.0 !important; }
        .fc-event { margin-bottom: 1px !important; padding: 0px 1px !important; border-radius: 2px !important; }
        .fc-list-table .duty-event, .fc-list-event.duty-event { display: none !important; }
    """

    # [요청사항] 탭 구성 변경
    tab1, tab2, tab3 = st.tabs(["📅 일정 & 당직", "🔥 업무 관리", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직 (모바일 가독성 최적화 버전)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 
        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 월간/주간 일정")
            if "selected_event" not in st.session_state:
                st.session_state.selected_event = None

            schedules = db.get_schedules()
            duties = db.get_duty_roster()
            calendar_events = []
            
            # 1. 일정 (Schedule)
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            if schedules:
                for s in schedules:
                    cat = s.get('category', '기타')
                    status = s.get('status', '진행중')
                    assignee = s.get('assignee', '')
                    
                    bg_color = color_map.get(cat, "#6b7280")
                    if status == '완료':
                        bg_color = "#9ca3af" # 완료된 업무는 회색 처리
                    
                    # 제목에 담당자 이름 포함
                    display_title = f"[{assignee}] {s['title']}" if assignee else s['title']
                    if status == '완료': display_title = "✅ " + display_title

                    calendar_events.append({
                        "title": display_title,
                        "start": s['start_time'],
                        "end": s['end_time'],
                        "backgroundColor": bg_color,
                        "borderColor": bg_color,
                        "classNames": ["schedule-event"],
                        "extendedProps": {
                            "type": "schedule", "id": str(s['id']), "real_title": s['title'],
                            "description": s.get('description', ''), "user": s.get('created_by', ''),
                            "category": cat, "location": s.get('location', ''),
                            "status": status, "assignee": assignee
                        }
                    })

            # 2. 당직 (Duty)
            if duties:
                for d in duties:
                    calendar_events.append({
                        "title": f"👮‍♂️ {d['worker_name']}",
                        "start": d['date'], "allDay": True,
                        "backgroundColor": "#16a34a", "borderColor": "#16a34a", "display": "block",
                        "classNames": ["duty-event"], 
                        "extendedProps": { "type": "duty", "id": str(d['id']), "worker_name": d['worker_name'], "date": d['date'] }
                    })

            cal_state = calendar(
                events=calendar_events, 
                options={
                    "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,dayGridWeek,listMonth"},
                    "buttonText": {"today": "오늘", "dayGridMonth": "월간", "dayGridWeek": "주간", "listMonth": "리스트"},
                    "initialView": "dayGridMonth", "locale": "ko", "showNonCurrentDates": False, "fixedWeekCount": False, "dayMaxEvents": 4
                }, 
                custom_css=calendar_custom_css, 
                key="my_calendar_v283"
            )

            if cal_state.get("eventClick"):
                st.session_state.selected_event = cal_state["eventClick"]["event"]

            # --- 일정 수정 팝업 ---
            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                e_type = props.get("type", "schedule")

                st.divider()
                if e_type == "schedule":
                    c_head, c_close = st.columns([9, 1])
                    c_head.info(f"✏️ **업무 수정 및 상태 변경**")
                    if c_close.button("❌", key="close_sch"): st.session_state.selected_event = None; st.rerun()

                    with st.form(key=f"edit_sch_{props['id']}"):
                        e_title = st.text_input("제목", value=props['real_title'])
                        c_a, c_b = st.columns(2)
                        cat_opts = ["점검", "월간", "회의", "행사", "기타", "직접입력"]
                        e_cat_select = c_a.selectbox("분류", cat_opts, index=cat_opts.index(props['category']) if props['category'] in cat_opts else 5)
                        stat_opts = ["진행중", "완료"]
                        e_status = c_b.selectbox("상태", stat_opts, index=stat_opts.index(props.get('status', '진행중')))
                        
                        c_c, c_d = st.columns(2)
                        e_loc = c_c.text_input("장소", value=props.get('location', ''))
                        e_assignee = c_d.text_input("담당자", value=props.get('assignee', ''))
                        e_desc = st.text_area("내용", value=props['description'])
                        
                        cb1, cb2 = st.columns(2)
                        if cb1.form_submit_button("저장"):
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), e_cat_select, e_desc, e_loc, e_status, e_assignee):
                                st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        if cb2.form_submit_button("삭제"):
                            db.delete_schedule(props['id']); st.success("삭제됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

        # === [우측] 관리 패널 ===
        with c2:
            st.markdown("### ➕ 일정 등록")
            cat_select = st.selectbox("분류", ["점검", "월간", "회의", "행사", "기타", "직접입력"], key="n_cat")
            n_title = st.text_input("제목", key="n_tit")
            c_l, c_as = st.columns(2)
            n_loc = c_l.text_input("장소", key="n_loc")
            n_assignee = c_as.text_input("담당자", key="n_asgn")
            
            nd1, nt1 = st.columns(2)
            n_date = nd1.date_input("날짜", key="n_d")
            time_options = [f"{h:02d}:{m:02d}" for h in range(7, 22) for m in (0, 30)] # 30분 단위
            n_time_str = nt1.selectbox("시간", time_options, index=6, key="n_t_sel")
            
            if st.button("저장", type="primary", use_container_width=True):
                if n_title:
                    h, m = map(int, n_time_str.split(':'))
                    start = datetime.combine(n_date, datetime.now().replace(hour=h, minute=m).time())
                    db.add_schedule(n_title, start.isoformat(), (start + timedelta(hours=1)).isoformat(), cat_select, "", "관리자", n_loc, n_assignee)
                    st.success("저장됨"); time.sleep(0.5); st.rerun()

            st.divider()
            st.markdown("### 👮‍♂️ 당직 관리")
            uploaded_file = st.file_uploader("엑셀 업로드", type=['xlsx'], key="duty_up")
            if uploaded_file and st.button("당직표 반영"):
                df = pd.read_excel(uploaded_file)
                for _, row in df.iterrows(): db.set_duty_worker(pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d"), str(row.iloc[1]))
                st.success("반영 완료!"); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 업무 관리 (추적 및 완료 체크 전용)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("🔥 현재 진행 중인 업무")
        st.caption("진행 중인 업무를 확인하고 즉시 완료 처리할 수 있습니다.")
        
        all_sch = db.get_schedules()
        # 미완료된 업무만 필터링
        pending_tasks = [s for s in all_sch if s.get('status', '진행중') == '진행중']
        
        if not pending_tasks:
            st.success("🎉 모든 업무가 완료되었습니다!")
        else:
            # 담당자 필터
            assignees = sorted(list(set([t.get('assignee') or "미지정" for t in pending_tasks])))
            filter_name = st.multiselect("👤 담당자별 보기", options=assignees)
            
            display_tasks = [t for t in pending_tasks if (t.get('assignee') or "미지정") in filter_name] if filter_name else pending_tasks
            
            for task in display_tasks:
                with st.container():
                    st.markdown(f"""
                    <div class="task-card">
                        <b>📍 {task.get('location', '위치미정')}</b> | {task['title']}<br>
                        <small>📅 {task['start_time'][:10]} | 👤 {task.get('assignee', '미정')}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"✅ 업무 완료하기", key=f"done_btn_{task['id']}", use_container_width=True):
                        # DB 업데이트 (상태만 '완료'로 변경)
                        db.update_schedule(
                            task['id'], task['title'], task['start_time'], task.get('end_time'),
                            task.get('category'), task.get('description'), task.get('location'),
                            "완료", task.get('assignee')
                        )
                        st.balloons(); st.success("고생하셨습니다! 완료 처리되었습니다."); time.sleep(0.5); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 3] 연락처 관리 (기존 검색 최적화 유지)
    # ------------------------------------------------------------------
    with tab3:
        st.subheader("📒 업체 연락처")
        if "edit_contact_id" not in st.session_state: st.session_state.edit_contact_id = None
        search_txt = st.text_input("🔍 검색 (업체, 담당자, 태그...)", placeholder="검색어를 입력하세요.")
        
        if not search_txt:
            st.info("👆 검색어를 입력하시면 리스트가 나타납니다.")
        else:
            all_contacts = db.get_contacts()
            filtered = [c for c in all_contacts if search_txt.lower() in f"{c.get('company_name')} {c.get('person_name')} {c.get('tags')}".lower()]
            if not filtered: st.warning("결과가 없습니다.")
            else:
                for c in filtered:
                    c_id = c['id']
                    if st.session_state.edit_contact_id != c_id:
                        with st.container(border=True):
                            c1, c2 = st.columns([5, 1])
                            with c1:
                                st.markdown(f"**{c.get('company_name')}** ({c.get('rank', '')})")
                                st.markdown(f"👤 {c.get('person_name')}")
                                if c.get('phone'):
                                    st.markdown(f'<a href="tel:{re.sub(r"[^0-9]", "", str(c["phone"]))}" target="_self" class="custom-phone-btn">📞 {c["phone"]}</a>', unsafe_allow_html=True)
                            if c2.button("✏️", key=f"e_{c_id}"): st.session_state.edit_contact_id = c_id; st.rerun()
                    else:
                        with st.form(key=f"f_{c_id}"):
                            e_comp = st.text_input("업체명", value=c['company_name'])
                            e_name = st.text_input("담당자", value=c.get('person_name',''))
                            e_phone = st.text_input("전화번호", value=c.get('phone',''))
                            if st.form_submit_button("저장"):
                                db.update_contact(c_id, e_comp, e_name, e_phone, c.get('email'), c.get('tags'), c.get('memo'), c.get('rank'))
                                st.session_state.edit_contact_id = None; st.success("수정됨"); st.rerun()
