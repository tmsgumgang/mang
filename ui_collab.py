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
    # [CSS 1] 메인 화면 스타일 (캘린더 외부 & 버튼 스타일)
    st.markdown("""<style>
        .meta-info {
            font-size: 0.85rem; color: gray; margin-top: 4px;
        }
        /* 전화 걸기 버튼 스타일 (st.markdown용) */
        a.custom-phone-btn {
            display: block;
            width: 100%;
            background-color: #3b82f6;
            color: white !important;
            text-decoration: none !important;
            text-align: center;
            padding: 8px 0;
            border-radius: 8px;
            font-weight: bold;
            margin-top: 5px;
            transition: background 0.3s;
        }
        a.custom-phone-btn:hover {
            background-color: #2563eb;
        }
        a.custom-phone-btn:active {
            background-color: #1d4ed8;
        }
    </style>""", unsafe_allow_html=True)

    # [CSS 2] 캘린더 내부 주입용 CSS (요청사항 반영)
    calendar_custom_css = """
        /* 헤더 최소화 */
        .fc-header-toolbar {
            flex-direction: column !important;
            gap: 2px !important;
            margin-bottom: 5px !important;
        }
        .fc-toolbar-title { font-size: 0.9rem !important; }
        .fc-button { font-size: 0.6rem !important; padding: 1px 5px !important; }

        /* [요청 1] 칸 높이 100px로 강제 확장 */
        .fc-daygrid-day-frame {
            min-height: 100px !important;
        }

        /* [요청 2] 폰트 크기 0.4rem (약 6px) - 아주 작게 */
        .fc-col-header-cell-cushion { /* 요일 */
            font-size: 0.5rem !important; 
            padding: 1px !important;
        }
        .fc-daygrid-day-number { /* 날짜 숫자 */
            font-size: 0.5rem !important; 
            padding: 1px !important;
        }
        .fc-event-title, .fc-event-time { /* 일정 내용 */
            font-size: 0.4rem !important; 
            font-weight: normal !important;
            line-height: 1.0 !important;
            white-space: nowrap !important; /* 줄바꿈 방지 */
        }
        
        /* 이벤트 박스 여백 제거 */
        .fc-event {
            margin-bottom: 1px !important;
            padding: 0px 1px !important;
        }

        /* 리스트 뷰에서 당직 숨김 */
        .fc-list-table .duty-event { display: none !important; }
        .fc-list-event.duty-event { display: none !important; }
    """

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 & 당직", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 

        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 월간/주간 일정")
            st.caption("💡 모바일: 우측 상단 **'주간(Week)'** 버튼 추천 / 리스트에는 일정만 표시됩니다.")

            if "selected_event" not in st.session_state:
                st.session_state.selected_event = None

            schedules = db.get_schedules()
            duties = db.get_duty_roster()
            
            calendar_events = []
            
            # 1. 일정
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            if schedules:
                for s in schedules:
                    cat = s.get('category', '기타')
                    calendar_events.append({
                        "title": f"[{cat}] {s['title']}",
                        "start": s['start_time'],
                        "end": s['end_time'],
                        "backgroundColor": color_map.get(cat, "#6b7280"),
                        "borderColor": color_map.get(cat, "#6b7280"),
                        "classNames": ["schedule-event"],
                        "extendedProps": {
                            "type": "schedule",
                            "id": str(s['id']),
                            "real_title": s['title'],
                            "description": s.get('description', ''),
                            "user": s.get('created_by', ''),
                            "category": cat,
                            "location": s.get('location', '')
                        }
                    })

            # 2. 당직
            if duties:
                for d in duties:
                    calendar_events.append({
                        "title": f"👮‍♂️ {d['worker_name']}",
                        "start": d['date'],
                        "allDay": True,
                        "backgroundColor": "#16a34a",
                        "borderColor": "#16a34a",
                        "display": "block",
                        "classNames": ["duty-event"], 
                        "extendedProps": {
                            "type": "duty",
                            "id": str(d['id']),
                            "worker_name": d['worker_name'],
                            "date": d['date']
                        }
                    })

            # 캘린더 옵션
            calendar_options = {
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,dayGridWeek,listMonth"
                },
                "buttonText": {
                    "today": "오늘",
                    "dayGridMonth": "월간",
                    "dayGridWeek": "주간",
                    "listMonth": "리스트(일정)"
                },
                "initialView": "dayGridMonth",
                "locale": "ko",
                "navLinks": True, 
                "selectable": True, 
                # [요청] 이번 달만 표시 (이전/다음달 숨김)
                "showNonCurrentDates": False, 
                # [요청] 6주 강제 채우기 끔
                "fixedWeekCount": False,
                # [요청] 칸을 늘렸으니 최대 5개까지 표시
                "dayMaxEvents": 5, 
                "height": "auto",
                "contentHeight": "auto"
            }
            
            # CSS 주입
            cal_state = calendar(
                events=calendar_events, 
                options=calendar_options, 
                custom_css=calendar_custom_css, 
                key="my_calendar_v277"
            )

            if cal_state.get("eventClick"):
                st.session_state.selected_event = cal_state["eventClick"]["event"]

            # --- 수정 폼 ---
            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                e_type = props.get("type", "schedule")

                st.divider()
                if e_type == "schedule":
                    c_head, c_close = st.columns([9, 1])
                    c_head.info(f"✏️ **일정 수정**")
                    if c_close.button("❌", key="close_sch"):
                        st.session_state.selected_event = None
                        st.rerun()

                    with st.form(key=f"edit_sch_{props['id']}"):
                        e_title = st.text_input("제목", value=props['real_title'])
                        cat_opts = ["점검", "월간", "회의", "행사", "기타", "직접입력"]
                        curr_cat = props['category']
                        idx = cat_opts.index(curr_cat) if curr_cat in cat_opts else 5
                        e_cat_select = st.selectbox("분류", cat_opts, index=idx)
                        e_cat_manual = ""
                        if e_cat_select == "직접입력":
                            e_cat_manual = st.text_input("직접 입력", value=curr_cat if curr_cat not in cat_opts[:-1] else "")
                        
                        e_loc = st.text_input("장소", value=props.get('location', ''))
                        e_desc = st.text_area("내용", value=props['description'])
                        
                        c_b1, c_b2 = st.columns(2)
                        if c_b1.form_submit_button("수정 저장"):
                            final_cat = e_cat_manual if e_cat_select == "직접입력" else e_cat_select
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), final_cat, e_desc, e_loc):
                                st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        if c_b2.form_submit_button("삭제"):
                            db.delete_schedule(props['id'])
                            st.success("삭제됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

                elif e_type == "duty":
                    c_head, c_close = st.columns([9, 1])
                    c_head.success(f"👮‍♂️ **당직 수정**")
                    if c_close.button("❌", key="close_duty"):
                        st.session_state.selected_event = None
                        st.rerun()
                    with st.form(key=f"edit_duty_{props['id']}"):
                        new_name = st.text_input("근무자", value=props['worker_name'])
                        c1, c2 = st.columns(2)
                        if c1.form_submit_button("수정"):
                            db.set_duty_worker(props['date'], new_name)
                            st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        if c2.form_submit_button("삭제"):
                            db.delete_duty_worker(props['id'])
                            st.rerun()

        # === [우측] 관리 패널 ===
        with c2:
            st.markdown("### 👮‍♂️ 당직 관리")
            d_tab1, d_tab2 = st.tabs(["📥 엑셀", "✍️ 수동"])
            with d_tab1:
                uploaded_file = st.file_uploader("당직표(A:날짜, B:이름)", type=['xlsx'])
                if uploaded_file and st.button("업로드"):
                    try:
                        df = pd.read_excel(uploaded_file)
                        for _, row in df.iterrows():
                            db.set_duty_worker(pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d"), str(row.iloc[1]))
                        st.success("완료!"); time.sleep(1); st.rerun()
                    except: st.error("오류 발생")
            with d_tab2:
                m_date = st.date_input("날짜", value=datetime.now().date())
                m_name = st.text_input("이름")
                if st.button("등록"):
                    if m_name:
                        db.set_duty_worker(str(m_date), m_name)
                        st.success("등록됨"); time.sleep(0.5); st.rerun()

            st.divider()
            st.markdown("### ➕ 일정 등록")
            cat_select = st.selectbox("분류", ["점검", "월간", "회의", "행사", "기타", "직접입력"], key="n_cat")
            cat_manual = st.text_input("분류명", key="n_man") if cat_select == "직접입력" else ""
            n_title = st.text_input("제목", key="n_tit")
            n_loc = st.text_input("장소", key="n_loc")
            nd1, nt1 = st.columns(2)
            n_date = nd1.date_input("날짜", key="n_d")
            n_time = nt1.time_input("시간", value=datetime.now().time(), key="n_t")
            n_desc = st.text_area("내용", key="n_dsc")
            n_user = st.text_input("등록자", "관리자", key="n_usr")
            
            if st.button("저장", type="primary", use_container_width=True):
                if n_title:
                    f_cat = cat_manual if cat_select == "직접입력" else cat_select
                    start = datetime.combine(n_date, n_time)
                    end = start + timedelta(hours=1)
                    db.add_schedule(n_title, start.isoformat(), end.isoformat(), f_cat, n_desc, n_user, n_loc)
                    st.success("저장됨"); time.sleep(0.5); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리 (V277: target="_self" 적용)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("📒 업체 연락처")
        
        if "edit_contact_id" not in st.session_state:
            st.session_state.edit_contact_id = None

        search_txt = st.text_input("🔍 검색", placeholder="업체, 담당자, 태그...")
        all_contacts = db.get_contacts()
        
        filtered = [c for c in all_contacts if search_txt.lower() in f"{c.get('company_name')} {c.get('person_name')} {c.get('tags')}".lower()] if search_txt else all_contacts

        if not filtered:
            st.info("데이터가 없습니다.")
        else:
            for c in filtered:
                c_id = c['id']
                
                # --- [A] 일반 보기 모드 ---
                if st.session_state.edit_contact_id != c_id:
                    with st.container(border=True):
                        # 레이아웃: 정보(왼쪽) + 수정버튼(오른쪽)
                        c_col1, c_col2 = st.columns([5, 1])
                        
                        with c_col1:
                            # 1. 업체 및 담당자 정보
                            st.markdown(f"**{c.get('company_name')}**")
                            rank_txt = f"({c.get('rank')})" if c.get('rank') else ""
                            st.markdown(f"👤 {c.get('person_name')} {rank_txt}")
                            
                            # 2. 전화번호 (st.markdown + HTML 버튼)
                            # [핵심 Fix] target="_self"를 사용하여 새 창 열림을 방지하고 즉시 전화 앱 호출
                            phone = c.get('phone', '')
                            if phone:
                                clean_phone = re.sub(r'[^0-9]', '', str(phone))
                                st.markdown(f'''
                                    <a href="tel:{clean_phone}" target="_self" class="custom-phone-btn">
                                        📞 {phone}
                                    </a>
                                ''', unsafe_allow_html=True)
                            else:
                                st.caption("번호 없음")
                                
                            # 3. 추가 정보
                            if c.get('email'):
                                st.markdown(f"<div class='meta-info'>📧 {c.get('email')}</div>", unsafe_allow_html=True)
                            if c.get('tags'):
                                st.markdown(f"<div class='meta-info'>🏷️ {c.get('tags')}</div>", unsafe_allow_html=True)
                            if c.get('memo'):
                                st.markdown(f"<div class='meta-info'>📝 {c.get('memo')}</div>", unsafe_allow_html=True)
                        
                        with c_col2:
                            if st.button("✏️", key=f"btn_edit_{c_id}", help="수정"):
                                st.session_state.edit_contact_id = c_id
                                st.rerun()

                # --- [B] 수정 모드 (기존 유지) ---
                else:
                    with st.container(border=True):
                        st.info("✏️ 연락처 수정")
                        with st.form(key=f"edit_con_form_{c_id}"):
                            ec1, ec2 = st.columns(2)
                            e_comp = ec1.text_input("업체명", value=c['company_name'])
                            e_name = ec2.text_input("담당자", value=c.get('person_name',''))
                            ec3, ec4 = st.columns(2)
                            e_rank = ec3.text_input("직급", value=c.get('rank',''))
                            e_phone = ec4.text_input("전화번호", value=c.get('phone',''))
                            e_email = st.text_input("이메일", value=c.get('email',''))
                            e_tags = st.text_input("태그", value=c.get('tags',''))
                            e_memo = st.text_area("메모", value=c.get('memo',''))
                            
                            eb1, eb2, eb3 = st.columns([2, 2, 5])
                            if eb1.form_submit_button("💾 저장"):
                                db.update_contact(c_id, e_comp, e_name, e_phone, e_email, e_tags, e_memo, e_rank)
                                st.session_state.edit_contact_id = None
                                st.success("수정됨"); time.sleep(0.5); st.rerun()
                            if eb2.form_submit_button("취소"):
                                st.session_state.edit_contact_id = None
                                st.rerun()
                            if eb3.form_submit_button("🗑️ 삭제"):
                                db.delete_contact(c_id)
                                st.session_state.edit_contact_id = None
                                st.rerun()

        st.divider()
        with st.expander("➕ 새 연락처 등록하기"):
            with st.form("add_contact_new"):
                c1, c2 = st.columns(2)
                nc = c1.text_input("업체명 (필수)")
                nn = c2.text_input("담당자")
                c3, c4 = st.columns(2)
                nr = c3.text_input("직급")
                np = c4.text_input("전화번호")
                ne = st.text_input("이메일")
                nt = st.text_input("태그")
                nm = st.text_area("메모")
                
                if st.form_submit_button("저장하기", type="primary"):
                    if nc:
                        if db.add_contact(nc, nn, np, ne, nt, nm, nr):
                            st.success("저장되었습니다.")
                            time.sleep(0.5); st.rerun()
                    else:
                        st.error("업체명은 필수입니다.")
