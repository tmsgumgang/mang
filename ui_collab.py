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
        .duty-uploader { border: 2px dashed #cbd5e1; padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px; }
        /* 캘린더 폰트 사이즈 조정 */
        .fc-event-title { font-weight: bold; }
    </style>""", unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 & 당직", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직 관리 (V260 Final)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 

        c1, c2 = st.columns([3, 1.2]) 
        
        # === [좌측] 캘린더 시각화 ===
        with c1:
            st.subheader("📆 월간 일정 및 당직표")
            
            # [State] 클릭된 이벤트 관리
            if "selected_event" not in st.session_state:
                st.session_state.selected_event = None

            # 1. 데이터 가져오기 (일정 + 당직)
            schedules = db.get_schedules()
            duties = db.get_duty_roster() # db_services.py V260 업데이트 필요
            
            calendar_events = []
            
            # 2. 일정(Schedule) 이벤트 변환
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            if schedules:
                for s in schedules:
                    cat = s.get('category', '기타')
                    loc = s.get('location', '')
                    title_text = f"[{cat}] {s['title']}"
                    
                    calendar_events.append({
                        "title": title_text,
                        "start": s['start_time'],
                        "end": s['end_time'],
                        "backgroundColor": color_map.get(cat, "#6b7280"),
                        "borderColor": color_map.get(cat, "#6b7280"),
                        "extendedProps": {
                            "type": "schedule", # 구분자
                            "id": str(s['id']),
                            "real_title": s['title'],
                            "description": s.get('description', ''),
                            "user": s.get('created_by', ''),
                            "category": cat,
                            "location": loc
                        }
                    })

            # 3. 당직(Duty) 이벤트 변환
            if duties:
                for d in duties:
                    calendar_events.append({
                        "title": f"👮‍♂️ {d['worker_name']}",
                        "start": d['date'], # 날짜만 있음 (All Day)
                        "allDay": True,
                        "backgroundColor": "#16a34a", # 초록색 (당직)
                        "borderColor": "#16a34a",
                        "display": "block", # 블록 형태로 표시
                        "extendedProps": {
                            "type": "duty", # 구분자
                            "id": str(d['id']),
                            "worker_name": d['worker_name'],
                            "date": d['date']
                        }
                    })

            # 4. 캘린더 옵션 (한국어 적용)
            calendar_options = {
                "headerToolbar": {"left": "today prev,next", "center": "title", "right": "dayGridMonth,listMonth"},
                "initialView": "dayGridMonth",
                "locale": "ko", # [V260] 한국어 설정
                "navLinks": False, 
                "selectable": True, 
                "editable": False,
                "dayMaxEvents": True
            }
            
            cal_state = calendar(events=calendar_events, options=calendar_options, key="my_calendar")

            # 5. [클릭 이벤트 처리]
            if cal_state.get("eventClick"):
                # 클릭 시 Session State에 저장 (화면 리셋 방지)
                st.session_state.selected_event = cal_state["eventClick"]["event"]

            # 6. [상세/수정 폼 렌더링]
            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                e_type = props.get("type", "schedule")

                st.divider()
                
                # --- [A] 일반 일정 수정 ---
                if e_type == "schedule":
                    c_head, c_close = st.columns([9, 1])
                    c_head.info(f"✏️ **일정 수정: {props['real_title']}**")
                    if c_close.button("❌", key="close_sch"):
                        st.session_state.selected_event = None
                        st.rerun()

                    with st.form(key=f"edit_sch_{props['id']}"):
                        ec1, ec2 = st.columns(2)
                        
                        # 날짜 파싱 (안전 처리)
                        try:
                            # '2024-02-06T10:00:00+09:00' -> T 기준 분리
                            orig_start = datetime.fromisoformat(evt['start'].split("T")[0])
                        except:
                            orig_start = datetime.now()

                        e_title = ec1.text_input("제목", value=props['real_title'])
                        
                        cat_opts = ["점검", "월간", "회의", "행사", "기타", "직접입력"]
                        curr_cat = props['category']
                        idx = cat_opts.index(curr_cat) if curr_cat in cat_opts else 5
                        e_cat_select = ec2.selectbox("분류", cat_opts, index=idx)
                        
                        e_cat_manual = ""
                        if e_cat_select == "직접입력":
                            e_cat_manual = st.text_input("분류 입력", value=curr_cat if curr_cat not in cat_opts[:-1] else "")
                        
                        e_loc = st.text_input("장소", value=props.get('location', ''))
                        e_desc = st.text_area("내용", value=props['description'])
                        
                        col_b1, col_b2 = st.columns([1, 5])
                        
                        if col_b1.form_submit_button("수정"):
                            final_cat = e_cat_manual if e_cat_select == "직접입력" else e_cat_select
                            # 시간은 수정하지 않는다고 가정 (날짜 이동은 캘린더 드래그앤드롭 구현 필요 - 여기선 내용 수정 위주)
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), final_cat, e_desc, e_loc):
                                st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        
                        if col_b2.form_submit_button("삭제"):
                            db.delete_schedule(props['id'])
                            st.success("삭제됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

                # --- [B] 당직 근무 수정 ---
                elif e_type == "duty":
                    c_head, c_close = st.columns([9, 1])
                    c_head.success(f"👮‍♂️ **당직 근무자 수정 ({props['date']})**")
                    if c_close.button("❌", key="close_duty"):
                        st.session_state.selected_event = None
                        st.rerun()

                    with st.form(key=f"edit_duty_{props['id']}"):
                        new_name = st.text_input("근무자 이름", value=props['worker_name'])
                        
                        c_btn1, c_btn2 = st.columns(2)
                        if c_btn1.form_submit_button("수정"):
                            db.set_duty_worker(props['date'], new_name)
                            st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        
                        if c_btn2.form_submit_button("삭제"):
                            db.delete_duty_worker(props['id'])
                            st.warning("삭제됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

        # === [우측] 입력 및 설정 패널 (st.form 제거됨!!) ===
        with c2:
            # 1. 엑셀 업로드 (당직)
            with st.expander("📥 당직표 엑셀 업로드", expanded=False):
                st.caption("형식: A열(날짜), B열(이름)")
                uploaded_file = st.file_uploader("엑셀 파일", type=['xlsx', 'xls'])
                if uploaded_file:
                    if st.button("업로드 적용"):
                        try:
                            df = pd.read_excel(uploaded_file)
                            count = 0
                            for _, row in df.iterrows():
                                d_date = pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d")
                                d_name = str(row.iloc[1])
                                if d_name and d_name != "nan":
                                    db.set_duty_worker(d_date, d_name)
                                    count += 1
                            st.success(f"{count}건 반영 완료!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"오류: {e}")

            st.divider()

            # 2. [V260 Fix] 일정 신규 등록 (st.form 제거 -> 즉시 반응)
            st.markdown("### ➕ 일정 등록")
            
            # (1) 분류 선택 (Form 밖이라서 선택 즉시 아래 코드가 실행됨)
            cat_select = st.selectbox("분류 선택", ["점검", "월간", "회의", "행사", "기타", "직접입력"], key="new_cat_sel")
            
            cat_manual = ""
            if cat_select == "직접입력":
                # 바로 입력창이 뜹니다!
                cat_manual = st.text_input("분류명 입력", placeholder="예: 긴급", key="new_cat_man")
            
            # (2) 나머지 정보 입력
            new_title = st.text_input("일정 제목", key="new_title")
            new_loc = st.text_input("장소 (선택)", key="new_loc")
            
            nd1, nt1 = st.columns(2)
            new_date = nd1.date_input("날짜", key="new_date")
            new_time = nt1.time_input("시간", value=datetime.now().time(), key="new_time")
            
            # 종료 시간 (기본 +1시간)
            new_end_time_val = (datetime.combine(new_date, new_time) + timedelta(hours=1)).time()
            end_time_input = st.time_input("종료 시간", value=new_end_time_val, key="new_end_time")
            
            new_desc = st.text_area("상세 내용", key="new_desc")
            new_user = st.text_input("등록자", "관리자", key="new_user")
            
            # (3) 저장 버튼 (Form 제출이 아닌 일반 버튼 클릭)
            if st.button("일정 저장 (Save)", use_container_width=True, type="primary"):
                if not new_title:
                    st.error("제목을 입력하세요.")
                else:
                    final_cat = cat_manual if cat_select == "직접입력" else cat_select
                    if not final_cat: final_cat = "기타"
                    
                    dt_start = datetime.combine(new_date, new_time)
                    dt_end = datetime.combine(new_date, end_time_input)
                    if dt_end < dt_start: dt_end += timedelta(days=1) # 다음날로 처리

                    if db.add_schedule(new_title, dt_start.isoformat(), dt_end.isoformat(), final_cat, new_desc, new_user, new_loc):
                        st.success("등록되었습니다!")
                        time.sleep(0.5)
                        st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리 (기존 유지)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("📒 주요 업체 및 담당자 연락처")
        search_txt = st.text_input("🔍 연락처 검색", placeholder="업체명, 담당자, 태그 등")
        
        all_contacts = db.get_contacts()
        filtered = []
        if search_txt:
            search_txt = search_txt.lower()
            for c in all_contacts:
                raw = f"{c.get('company_name','')} {c.get('person_name','')} {c.get('tags','')}".lower()
                if search_txt in raw:
                    filtered.append(c)
        else:
            filtered = all_contacts

        if filtered:
            df_con = pd.DataFrame(filtered)
            cols = ['id', 'company_name', 'person_name', 'phone', 'email', 'tags', 'memo']
            valid_cols = [c for c in cols if c in df_con.columns]
            display_df = df_con[valid_cols].copy()
            display_df.rename(columns={'id':'ID', 'company_name':'업체명', 'person_name':'담당자', 'phone':'전화번호', 'email':'이메일', 'tags':'태그', 'memo':'메모'}, inplace=True)
            
            st.data_editor(display_df, key="con_edit", use_container_width=True, hide_index=True, disabled=["ID"])
            if st.button("💾 새로고침"): st.rerun()
        else:
            st.info("데이터 없음")

        with st.expander("➕ 연락처 추가"):
            with st.form("add_con"):
                c1, c2 = st.columns(2)
                nc = c1.text_input("업체명")
                nn = c2.text_input("담당자")
                np = c1.text_input("전화번호")
                ne = c2.text_input("이메일")
                nt = st.text_input("태그")
                nm = st.text_area("메모")
                if st.form_submit_button("저장"):
                    if nc:
                        db.add_contact(nc, nn, np, ne, nt, nm)
                        st.success("저장됨")
                        time.sleep(0.5)
                        st.rerun()
