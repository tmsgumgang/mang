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
    # [Tab 1] 일정 관리 (V259 Upgraded - Fix disappearing logic)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 

        c1, c2 = st.columns([2.5, 1]) 
        
        # === [좌측] 캘린더 시각화 & 수정 ===
        with c1:
            st.subheader("📆 월간 일정표")
            
            # [State] 선택된 일정 ID 기억하기 (화면 리셋 방지)
            if "selected_sch_id" not in st.session_state:
                st.session_state.selected_sch_id = None

            schedules = db.get_schedules()
            calendar_events = []
            
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}

            if schedules:
                for s in schedules:
                    start_iso = s['start_time']
                    end_iso = s['end_time']
                    cat = s.get('category', '기타')
                    loc = s.get('location', '')
                    display_title = f"[{cat}] {s['title']}"
                    bg_color = color_map.get(cat, "#6b7280")

                    calendar_events.append({
                        "title": display_title,
                        "start": start_iso,
                        "end": end_iso,
                        "backgroundColor": bg_color,
                        "borderColor": bg_color,
                        "extendedProps": {"id": str(s['id'])} # [Fix] ID를 문자열로 통일
                    })

            calendar_options = {
                "headerToolbar": {"left": "today prev,next", "center": "title", "right": "dayGridMonth,timeGridWeek,listMonth"},
                "initialView": "dayGridMonth",
                "navLinks": True, "selectable": True, "editable": False,
            }
            
            cal_state = calendar(events=calendar_events, options=calendar_options, key="my_calendar")

            # [로직] 캘린더 클릭 시 -> 세션 스테이트에 ID 저장
            if cal_state.get("eventClick"):
                clicked_id = str(cal_state["eventClick"]["event"]["extendedProps"]["id"])
                st.session_state.selected_sch_id = clicked_id

            # [UI] 저장된 ID가 있으면 -> 수정 폼 렌더링
            if st.session_state.selected_sch_id is not None:
                # DB 데이터에서 해당 ID 찾기 (문자열 비교)
                target_sch = next((item for item in schedules if str(item["id"]) == st.session_state.selected_sch_id), None)
                
                if target_sch:
                    st.divider()
                    c_edit_head, c_close = st.columns([8, 1])
                    c_edit_head.info(f"✏️ **일정 수정: {target_sch['title']}**")
                    
                    # 닫기 버튼
                    if c_close.button("❌", key="close_edit"):
                        st.session_state.selected_sch_id = None
                        st.rerun()

                    with st.form(key=f"edit_schedule_form_{target_sch['id']}"):
                        ec1, ec2 = st.columns(2)
                        
                        try:
                            # 시간 파싱
                            orig_start = datetime.fromisoformat(target_sch['start_time'].replace('Z', '+00:00'))
                            orig_end = datetime.fromisoformat(target_sch['end_time'].replace('Z', '+00:00')) if target_sch.get('end_time') else orig_start + timedelta(hours=1)
                        except:
                            orig_start = datetime.now()
                            orig_end = datetime.now() + timedelta(hours=1)

                        e_title = ec1.text_input("제목", value=target_sch['title'])
                        
                        # 분류
                        cat_opts = ["점검", "월간", "회의", "행사", "기타", "직접입력"]
                        curr_cat = target_sch['category']
                        idx = cat_opts.index(curr_cat) if curr_cat in cat_opts else 5 # 없으면 '직접입력'
                        e_cat_select = ec2.selectbox("분류", cat_opts, index=idx)
                        
                        e_cat_manual = ""
                        if e_cat_select == "직접입력":
                            e_cat_manual = st.text_input("분류 직접 입력", value=curr_cat if curr_cat not in cat_opts[:-1] else "")
                        
                        e_loc = st.text_input("장소", value=target_sch.get('location', ''))
                        
                        ed1, et1, ed2, et2 = st.columns(4)
                        e_s_date = ed1.date_input("시작 날짜", value=orig_start.date())
                        e_s_time = et1.time_input("시작 시간", value=orig_start.time())
                        e_e_date = ed2.date_input("종료 날짜", value=orig_end.date())
                        e_e_time = et2.time_input("종료 시간", value=orig_end.time())
                        
                        e_desc = st.text_area("상세 내용", value=target_sch.get('description', ''))
                        
                        col_btn1, col_btn2 = st.columns([1, 5])
                        btn_update = col_btn1.form_submit_button("💾 수정 저장")
                        btn_del = col_btn2.form_submit_button("🗑️ 삭제")
                        
                        if btn_update:
                            final_cat = e_cat_manual if e_cat_select == "직접입력" else e_cat_select
                            if not final_cat: final_cat = "기타"
                            
                            new_start = datetime.combine(e_s_date, e_s_time).isoformat()
                            new_end = datetime.combine(e_e_date, e_e_time).isoformat()
                            
                            if db.update_schedule(target_sch['id'], e_title, new_start, new_end, final_cat, e_desc, e_loc):
                                st.success("수정되었습니다.")
                                st.session_state.selected_sch_id = None 
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("수정 실패")
                                
                        if btn_del:
                            if db.delete_schedule(target_sch['id']):
                                st.success("삭제되었습니다.")
                                st.session_state.selected_sch_id = None
                                time.sleep(0.5)
                                st.rerun()

        # === [우측] 일정 신규 등록 ===
        with c2:
            st.markdown("### ➕ 신규 등록")
            with st.form("add_schedule_form_cal"):
                s_title = st.text_input("일정 제목 (필수)")
                s_cat_select = st.selectbox("분류", ["점검", "월간", "회의", "행사", "기타", "직접입력"])
                s_cat_manual = ""
                if s_cat_select == "직접입력":
                    s_cat_manual = st.text_input("└ 분류명 입력", placeholder="예: 긴급")

                s_loc = st.text_input("장소 (선택)")

                st.markdown("---")
                now = datetime.now()
                next_hour = now + timedelta(hours=1)
                
                st.caption("시간 설정")
                d1, t1 = st.columns(2)
                s_date = d1.date_input("시작 날짜", value=now.date())
                s_time = t1.time_input("시작 시간", value=now.time())
                
                d2, t2 = st.columns(2)
                e_date = d2.date_input("종료 날짜", value=now.date())
                e_time = t2.time_input("종료 시간", value=next_hour.time())
                
                s_desc = st.text_area("상세 내용")
                s_user = st.text_input("등록자", "관리자")
                
                if st.form_submit_button("일정 추가"):
                    if not s_title:
                        st.error("제목은 필수입니다.")
                    else:
                        final_cat = s_cat_manual if s_cat_select == "직접입력" else s_cat_select
                        if not final_cat: final_cat = "기타"

                        dt_start = datetime.combine(s_date, s_time)
                        dt_end = datetime.combine(e_date, e_time)
                        
                        if dt_end < dt_start:
                            dt_end = dt_start + timedelta(hours=1)

                        if db.add_schedule(s_title, dt_start.isoformat(), dt_end.isoformat(), final_cat, s_desc, s_user, s_loc):
                            st.success("등록 완료!")
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
