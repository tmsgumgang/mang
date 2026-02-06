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
    # [CSS] 카드 디자인 및 스타일 정의
    st.markdown("""<style>
        /* 연락처 카드 스타일 */
        .contact-card {
            background-color: white;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            transition: transform 0.2s;
        }
        .contact-card:hover { transform: translateY(-2px); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .comp-name { font-size: 1.1rem; font-weight: bold; color: #1e293b; margin-bottom: 4px; }
        .person-name { font-size: 0.95rem; color: #64748b; margin-bottom: 8px; }
        .phone-link { 
            display: inline-block;
            background-color: #eff6ff; 
            color: #2563eb; 
            text-decoration: none; 
            font-weight: bold; 
            padding: 6px 12px; 
            border-radius: 20px; 
            margin: 5px 0;
            font-size: 1rem;
        }
        .phone-link:hover { background-color: #dbeafe; }
        .tag-badge { 
            display: inline-block; 
            background-color: #f1f5f9; 
            color: #475569; 
            padding: 2px 8px; 
            border-radius: 4px; 
            font-size: 0.8rem; 
            margin-right: 4px; 
        }
        .memo-text { font-size: 0.85rem; color: #94a3b8; margin-top: 8px; border-top: 1px solid #f1f5f9; padding-top: 4px; }
        
        /* 캘린더 모바일 폰트 조정 */
        .fc-toolbar-title { font-size: 1.2rem !important; }
        .fc-event { cursor: pointer; }
    </style>""", unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 & 당직", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직 관리 (V261)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 

        c1, c2 = st.columns([3, 1.2]) 
        
        # === [좌측] 캘린더 시각화 ===
        with c1:
            st.subheader("📆 월간 일정 및 당직표")
            
            # [Tip] 모바일 사용자 안내
            st.info("💡 모바일에서는 캘린더 우측 상단의 **'리스트'** 버튼을 누르면 일정을 보기 편합니다.", icon="📱")
            
            # [State] 클릭된 이벤트 관리
            if "selected_event" not in st.session_state:
                st.session_state.selected_event = None

            # 1. 데이터 가져오기
            schedules = db.get_schedules()
            duties = db.get_duty_roster()
            
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
                            "type": "schedule",
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
                        "start": d['date'],
                        "allDay": True,
                        "backgroundColor": "#16a34a", # 초록색
                        "borderColor": "#16a34a",
                        "display": "block",
                        "extendedProps": {
                            "type": "duty",
                            "id": str(d['id']),
                            "worker_name": d['worker_name'],
                            "date": d['date']
                        }
                    })

            # 4. 캘린더 옵션 (모바일 고려: listMonth 추가)
            calendar_options = {
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,listMonth" # 월간/리스트 뷰 전환 버튼
                },
                "buttonText": {
                    "today": "오늘",
                    "dayGridMonth": "월간",
                    "listMonth": "리스트(목록)"
                },
                "initialView": "dayGridMonth",
                "locale": "ko",
                "navLinks": False, 
                "selectable": True, 
                "editable": False,
                "dayMaxEvents": True
            }
            
            cal_state = calendar(events=calendar_events, options=calendar_options, key="my_calendar")

            # 5. [클릭 이벤트 처리]
            if cal_state.get("eventClick"):
                st.session_state.selected_event = cal_state["eventClick"]["event"]

            # 6. [상세/수정 폼]
            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                e_type = props.get("type", "schedule")

                st.divider()
                
                # [A] 일정 수정
                if e_type == "schedule":
                    c_head, c_close = st.columns([9, 1])
                    c_head.info(f"✏️ **일정 수정: {props['real_title']}**")
                    if c_close.button("❌", key="close_sch"):
                        st.session_state.selected_event = None
                        st.rerun()

                    with st.form(key=f"edit_sch_{props['id']}"):
                        ec1, ec2 = st.columns(2)
                        try:
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
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), final_cat, e_desc, e_loc):
                                st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        
                        if col_b2.form_submit_button("삭제"):
                            db.delete_schedule(props['id'])
                            st.success("삭제됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

                # [B] 당직 수정
                elif e_type == "duty":
                    c_head, c_close = st.columns([9, 1])
                    c_head.success(f"👮‍♂️ **당직 수정 ({props['date']})**")
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

        # === [우측] 관리 패널 ===
        with c2:
            st.markdown("### 👮‍♂️ 당직 관리")
            
            # [V261] 당직 등록 방식 탭 분리 (엑셀 / 수동)
            d_tab1, d_tab2 = st.tabs(["📥 엑셀 업로드", "✍️ 수동 입력"])
            
            with d_tab1:
                uploaded_file = st.file_uploader("당직표(A열:날짜, B열:이름)", type=['xlsx', 'xls'])
                if uploaded_file and st.button("업로드 적용", use_container_width=True):
                    try:
                        df = pd.read_excel(uploaded_file)
                        count = 0
                        for _, row in df.iterrows():
                            d_date = pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d")
                            d_name = str(row.iloc[1])
                            if d_name and d_name != "nan":
                                db.set_duty_worker(d_date, d_name)
                                count += 1
                        st.success(f"{count}건 등록 완료!")
                        time.sleep(1); st.rerun()
                    except Exception as e: st.error(f"오류: {e}")

            with d_tab2:
                # [V261] 수동 입력 기능
                m_date = st.date_input("당직 날짜", value=datetime.now().date())
                m_name = st.text_input("근무자 이름", placeholder="홍길동")
                if st.button("당직 등록", use_container_width=True):
                    if m_name:
                        db.set_duty_worker(str(m_date), m_name)
                        st.success(f"{m_date}: {m_name} 등록됨")
                        time.sleep(0.5); st.rerun()
                    else:
                        st.error("이름을 입력하세요.")

            st.divider()

            # [일정 등록] (기존 유지)
            st.markdown("### ➕ 일정 등록")
            cat_select = st.selectbox("분류", ["점검", "월간", "회의", "행사", "기타", "직접입력"], key="new_cat_sel")
            cat_manual = ""
            if cat_select == "직접입력":
                cat_manual = st.text_input("분류명", placeholder="예: 긴급", key="new_cat_man")
            
            new_title = st.text_input("제목", key="new_title")
            new_loc = st.text_input("장소", key="new_loc")
            
            nd1, nt1 = st.columns(2)
            new_date = nd1.date_input("날짜", key="new_date")
            new_time = nt1.time_input("시간", value=datetime.now().time(), key="new_time")
            
            new_end_time_val = (datetime.combine(new_date, new_time) + timedelta(hours=1)).time()
            end_time_input = st.time_input("종료 시간", value=new_end_time_val, key="new_end_time")
            
            new_desc = st.text_area("내용", key="new_desc")
            new_user = st.text_input("등록자", "관리자", key="new_user")
            
            if st.button("일정 저장", use_container_width=True, type="primary"):
                if not new_title:
                    st.error("제목 필수")
                else:
                    final_cat = cat_manual if cat_select == "직접입력" else cat_select
                    if not final_cat: final_cat = "기타"
                    
                    dt_start = datetime.combine(new_date, new_time)
                    dt_end = datetime.combine(new_date, end_time_input)
                    if dt_end < dt_start: dt_end += timedelta(days=1)

                    if db.add_schedule(new_title, dt_start.isoformat(), dt_end.isoformat(), final_cat, new_desc, new_user, new_loc):
                        st.success("등록 완료")
                        time.sleep(0.5); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리 (V261: Card Design & Call)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("📒 업체 및 담당자 연락처")
        
        c_search, c_add = st.columns([3, 1])
        search_txt = c_search.text_input("🔍 검색", placeholder="업체명, 담당자, 태그...")
        
        with c_add:
            # 추가 버튼 대신 Expander를 깔끔하게 사용
            pass 

        # 데이터 필터링
        all_contacts = db.get_contacts()
        filtered = []
        if search_txt:
            search_txt = search_txt.lower()
            for c in all_contacts:
                raw = f"{c.get('company_name','')} {c.get('person_name','')} {c.get('tags','')}".lower()
                if search_txt in raw: filtered.append(c)
        else:
            filtered = all_contacts

        if not filtered:
            st.info("등록된 연락처가 없습니다.")
        else:
            # [V261] 카드 그리드 뷰 (2열 배치)
            # 모바일에서는 자동으로 1열로 축소됨 (Streamlit column 특성)
            cols = st.columns(2)
            
            for idx, contact in enumerate(filtered):
                col = cols[idx % 2] # 0 또는 1 (왼쪽/오른쪽)
                
                with col:
                    # 데이터 준비
                    c_id = contact['id']
                    comp = contact.get('company_name', '업체명 없음')
                    name = contact.get('person_name', '-')
                    phone = contact.get('phone', '')
                    email = contact.get('email', '')
                    tags = contact.get('tags', '')
                    memo = contact.get('memo', '')
                    
                    # 태그 HTML 생성
                    tags_html = ""
                    if tags:
                        for t in tags.split(','):
                            tags_html += f"<span class='tag-badge'>#{t.strip()}</span>"

                    # HTML 카드 렌더링
                    st.markdown(f"""
                    <div class="contact-card">
                        <div class="comp-name">{comp}</div>
                        <div class="person-name">👤 {name}</div>
                        <a href="tel:{phone}" class="phone-link">📞 {phone if phone else '전화번호 없음'}</a>
                        <div style="font-size:0.9rem; margin-top:5px;">📧 {email if email else '-'}</div>
                        <div style="margin-top:8px;">{tags_html}</div>
                        <div class="memo-text">{memo}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 삭제 버튼 (카드 하단)
                    if st.button("🗑️ 삭제", key=f"del_con_{c_id}"):
                        if db.delete_contact(c_id):
                            st.success("삭제됨")
                            time.sleep(0.5)
                            st.rerun()

        st.divider()
        with st.expander("➕ 새 연락처 등록하기"):
            with st.form("add_contact_new"):
                c1, c2 = st.columns(2)
                nc = c1.text_input("업체명 (필수)")
                nn = c2.text_input("담당자")
                c3, c4 = st.columns(2)
                np = c3.text_input("전화번호 (010-0000-0000)")
                ne = c4.text_input("이메일")
                nt = st.text_input("태그 (쉼표 구분)")
                nm = st.text_area("메모")
                
                if st.form_submit_button("저장하기", type="primary"):
                    if nc:
                        if db.add_contact(nc, nn, np, ne, nt, nm):
                            st.success("저장되었습니다.")
                            time.sleep(0.5); st.rerun()
                    else:
                        st.error("업체명은 필수입니다.")
