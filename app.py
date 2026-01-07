import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re
import time

# [보안] Streamlit Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다.")
    st.stop()

@st.cache_resource
def init_clients():
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)
    chat_model = genai.GenerativeModel('gemini-2.0-flash') 
    return supabase_client, chat_model

try:
    supabase, ai_model = init_clients()
except Exception as e:
    st.error(f"시스템 연결 실패: {e}")

def keep_db_alive():
    try: supabase.table("knowledge_base").select("id").limit(1).execute()
    except: pass

def clean_text_for_db(text):
    if not text: return ""
    text = text.replace("\u0000", "")
    return "".join(ch for ch in text if ch.isprintable() or ch in ['\n', '\r', '\t']).strip()

def get_embedding(text):
    clean_txt = clean_text_for_db(text)
    if not clean_txt: return [0.0] * 768
    result = genai.embed_content(model="models/text-embedding-004", content=clean_txt, task_type="retrieval_document")
    return result['embedding']

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# [V90] 의도 분석
def analyze_query_v90(text):
    if not text: return False, False, None, None
    tech_keys = ["시마즈", "백년기술", "코비", "케이엔알", "YSI", "TOC", "TN", "TP", "VOC", "점검", "교체", "수리", "오류", "HATOX", "HATA", "ROBOCHEM", "SSR", "펌프", "밸브"]
    is_tech = any(k.lower() in text.lower() for k in tech_keys)
    life_keys = ["맛집", "식당", "카페", "추천", "금산", "옥천", "영동", "주차", "메뉴", "점심", "회식"]
    is_life_intent = any(k in text for k in life_keys)
    m_match = re.search(r'(\d{2,})', text)
    found_mod_num = m_match.group(1) if m_match else None
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    return is_tech, is_life_intent, found_mfr, found_mod_num

# [V90] 블랙리스트 관리
def add_to_blacklist(query, source_id):
    try:
        supabase.table("knowledge_blacklist").insert({"query": query, "source_id": source_id}).execute()
        return True
    except: return False

def get_blacklist(query):
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
        return [r['source_id'] for r in res.data]
    except: return []

def update_helpfulness(item_list):
    try:
        for item in item_list:
            table = "knowledge_base" if "solution" in item else "manual_base"
            curr = item.get('helpful_count', 0) or 0
            supabase.table(table).update({"helpful_count": curr + 1}).eq("id", item['id']).execute()
        return True
    except: return False

def log_unsolved(query, reason, is_life):
    try:
        exists = supabase.table("unsolved_questions").select("id").eq("query", query).eq("status", "대기중").execute().data
        if not exists:
            supabase.table("unsolved_questions").insert({"query": query, "reason": reason, "is_lifestyle": is_life}).execute()
    except: pass

def sync_qa_to_knowledge(q_id):
    try:
        q_d = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{'답글' if a.get('parent_id') else '조치'}] {a['author']}: {a['content']}" for a in ans_d]
        full_sync_txt = f"상황: {q_d['content']}\n해결:\n" + "\n".join(ans_list)
        is_t, is_l, mfr, mod = analyze_query_v90(q_d['title'] + q_d['content'])
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "맛집/정보" if (is_l and not is_t) else "게시판답변",
            "manufacturer": mfr if mfr else ("생활정보" if is_l else "현장장비"),
            "model_name": q_d.get('category', '일반'), "issue": q_d['title'],
            "solution": full_sync_txt, "registered_by": q_d['author'],
            "embedding": get_embedding(f"{mfr} {q_d['title']} {full_sync_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.8rem !important; }
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-exp { background-color: #e0f2fe; color: #0369a1; }
    .tag-man { background-color: #fef3c7; color: #92400e; }
    .tag-qa { background-color: #f5f3ff; color: #5b21b6; }
    .tag-info { background-color: #f0fdf4; color: #166534; }
    .sentence-row { padding: 8px; border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; justify-content: space-between; }
    .exclude-btn { font-size: 0.7rem !important; color: #ef4444 !important; border: 1px solid #fee2e2 !important; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V90: 정밀 교정 모드) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("정밀 탐색 중..."):
            try:
                is_tech_q, is_life_q, target_mfr, target_mod_num = analyze_query_v90(user_q)
                is_life = True if "생활정보" in search_mode else False
                query_vec = get_embedding(user_q)
                
                # [V90] 블랙리스트 데이터 조회
                blacklist_ids = get_blacklist(user_q)
                
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 50}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 30}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()

                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    
                    # [V90 핵심] 블랙리스트 필터링: 과거 성주 님이 제외한 정보는 원천 차단
                    if u_key in blacklist_ids: continue
                    
                    cat, mfr, mod, iss = str(d.get('category') or '현장경험'), str(d.get('manufacturer') or '현장장비'), str(d.get('model_name') or '일반').upper(), str(d.get('issue') or '')
                    if not is_life and cat == "맛집/정보": continue
                    elif is_life and cat != "맛집/정보": continue
                    
                    keyword_hit = target_mfr and (target_mfr in mfr or target_mfr in iss)
                    model_hit = target_mod_num and target_mod_num in mod
                    is_conflict = target_mfr and any(comp in mfr and comp != target_mfr for comp in ["시마즈", "백년기술", "코비", "케이엔알", "YSI"])
                    is_generic = any(gen in mfr for gen in ["현장장비", "미분류", "기타", "커뮤니티", "생활정보"])
                    
                    if keyword_hit or model_hit or is_generic or not is_conflict:
                        raw_c = d.get('solution') or d.get('content') or ""
                        f_print = "".join(raw_c.split())[:60]
                        if u_key not in seen_ks and f_print not in seen_fps:
                            bonus = 0.5 if keyword_hit else 0
                            d['final_score'] = (d.get('similarity') or 0) + bonus + ((d.get('helpful_count') or 0) * 0.01)
                            d['source_id_tag'] = u_key # UI용 고유 태그 저장
                            final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)

                if final_pool:
                    context = "\n".join([f"[{d['source_id_tag']}]: {d.get('solution') or d.get('content')}" for d in final_pool[:12]])
                    # [V90] AI에게 문장별로 출처 번호를 남기도록 지시
                    ans_p = f"""금강수계 수질 전문가입니다. 
                    1. 질문({user_q})에 대해 제공된 데이터를 요약하여 답변하세요.
                    2. 각 문장 끝에는 반드시 근거가 된 데이터의 태그(예: [EXP_12])를 적으세요.
                    3. 데이터에 식당 정보가 섞여 있어도 질문과 무관하면 언급하지 마세요.
                    데이터: {context}"""
                    
                    raw_response = ai_model.generate_content(ans_p).text
                    sentences = [s.strip() for s in raw_response.split('\n') if s.strip()]

                    # [V90 핵심] 정밀 교정 UI
                    st.subheader("🤖 AI 정밀 요약 답변")
                    for i, sent in enumerate(sentences):
                        with st.container():
                            col_txt, col_btn = st.columns([0.85, 0.15])
                            col_txt.write(sent)
                            # 문장에서 출처 태그 추출 (예: [EXP_105])
                            match = re.search(r'\[(EXP_\d+|MAN_\d+)\]', sent)
                            if match:
                                s_id = match.group(1)
                                if col_btn.button("제외", key=f"ex_{i}_{s_id}", help="이 정보는 이 질문과 관련 없습니다."):
                                    if add_to_blacklist(user_q, s_id):
                                        st.error(f"'{s_id}' 정보를 이 질문의 검색 대상에서 제외했습니다."); time.sleep(1); st.rerun()
                    
                    st.write("---")
                    c_f1, c_f2 = st.columns([0.5, 0.5])
                    if c_f1.button("👍 전체 답변이 도움됨", use_container_width=True):
                        update_helpfulness(final_pool[:3]); st.success("반영!"); time.sleep(0.5); st.rerun()
                    if c_f2.button("👎 답변이 너무 부족함 (SOS)", use_container_width=True):
                        log_unsolved(user_q, "사용자 불만족", is_life); st.warning("미해결 과제 등록!"); time.sleep(0.5); st.rerun()

                    st.markdown("---")
                    for d in final_pool[:10]:
                        t_n = "게시판" if d.get('qa_id') else ("매뉴얼" if 'content' in d else "현장경험")
                        with st.expander(f"[{t_n}] {d.get('manufacturer') or '기타'} | {d['source_id_tag']}"):
                            st.write(d.get('solution') or d.get('content'))
                else:
                    st.warning("⚠️ 지식을 찾지 못했습니다. 미해결 과제로 등록되었습니다.")
                    log_unsolved(user_q, "검색결과 없음", is_life)
            except Exception as e: st.error(f"조회 실패 (V90): {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    with st.form("reg_v90", clear_on_submit=True):
        if cat_sel != "맛집/정보":
            c1, c2 = st.columns(2)
            m_sel = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            m_man = c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목")
        else:
            c1, c2 = st.columns(2)
            res_n, res_l, res_m = c1.text_input("식당명"), c2.text_input("위치"), st.text_input("대표메뉴")
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("✅ 저장"):
            final_m = (m_man if m_sel == "직접 입력" else m_sel) if cat_sel != "맛집/정보" else res_n
            final_mod, final_it = (model_n, item_n) if cat_sel != "맛집/정보" else (res_l, res_m)
            if final_m and iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": clean_text_for_db(final_m), "model_name": clean_text_for_db(final_mod), "measurement_item": clean_text_for_db(final_it), "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": clean_text_for_db(reg_n), "embedding": get_embedding(f"{cat_sel} {final_m} {final_mod} {iss_t} {sol_d}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서 등록 ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("정보 분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_reader.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"제조사/모델명 JSON: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        c1, c2 = st.columns(2)
        f_mfr, f_model = st.text_input("🏢 제조사", value=st.session_state.s_m), st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        if st.button("🚀 저장"):
            with st.status("📑 저장 중...") as status:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                all_t = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
                chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
                for i, chunk in enumerate(chunks):
                    supabase.table("manual_base").insert({"manufacturer": f_mfr, "model_name": f_model, "content": clean_text_for_db(chunk), "file_name": up_f.name, "page_num": (i//2)+1, "embedding": get_embedding(chunk)}).execute()
                st.success("✅ 완료!"); st.rerun()

# --- 4. 데이터 전체 관리 ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    if st.button("🔄 게시판 지식 재동기화"):
        qa_list = supabase.table("qa_board").select("id").execute().data
        for qa in qa_list: sync_qa_to_knowledge(qa['id'])
        st.success("✅ 완료!")
    t1, t2, t3, t4 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 블랙리스트 관리"])
    with t1:
        logs_data = supabase.table("search_logs").select("*").order("created_at", desc=True).limit(30).execute().data
        if logs_data:
            df = pd.DataFrame(logs_data)
            df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
            df['is_lifestyle'] = df['is_lifestyle'].map({True: "🍴 생활", False: "🛠️ 업무"})
            st.dataframe(df.rename(columns={'created_at': '일시', 'query': '검색어', 'is_lifestyle': '모드'})[['일시', '검색어', '모드']], use_container_width=True)
    with t2:
        ms = st.text_input("🔍 경험 수정")
        if ms:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{ms}%,issue.ilike.%{ms}%").execute()
            for r in res.data:
                with st.expander(f"[{r.get('manufacturer')}] {r['issue']}"):
                    with st.form(f"ed_e_{r['id']}"):
                        e_mfr, e_mod, e_sol = st.text_input("제조사", value=r.get('manufacturer') or ""), st.text_input("모델명", value=r.get('model_name') or ""), st.text_area("내용", value=r.get('solution') or "")
                        if st.form_submit_button("💾 갱신"):
                            new_vec = get_embedding(f"{r.get('category')} {e_mfr} {e_mod} {r['issue']} {e_sol}")
                            supabase.table("knowledge_base").update({"manufacturer": e_mfr, "model_name": e_mod, "solution": e_sol, "embedding": new_vec}).eq("id", r['id']).execute(); st.rerun()
                    if st.button("🗑️ 삭제", key=f"del_e_{r['id']}"): supabase.table("knowledge_base").delete().eq("id", r['id']).execute(); st.rerun()
    with t3:
        ds = st.text_input("🔍 매뉴얼 수정")
        if ds:
            res = supabase.table("manual_base").select("*").or_(f"manufacturer.ilike.%{ds}%,file_name.ilike.%{ds}%").execute()
            for f in list(set([r['file_name'] for r in res.data])):
                s = next(r for r in res.data if r['file_name'] == f)
                with st.expander(f"📄 {f}"):
                    with st.form(f"ed_m_{f}"):
                        new_mfr, new_mod = st.text_input("제조사", value=s.get('manufacturer') or ""), st.text_input("모델명", value=s.get('model_name') or "")
                        if st.form_submit_button("💾 전체 갱신"):
                            supabase.table("manual_base").update({"manufacturer": new_mfr, "model_name": new_mod}).eq("file_name", f).execute(); st.rerun()
    with t4:
        st.subheader("🚫 제외된 지식 리스트")
        bl = supabase.table("knowledge_blacklist").select("*").order("created_at", desc=True).execute().data
        if bl:
            st.dataframe(pd.DataFrame(bl)[['query', 'source_id', 'created_at']], use_container_width=True)
            if st.button("🗑️ 블랙리스트 전체 초기화"): supabase.table("knowledge_blacklist").delete().neq("id", 0).execute(); st.rerun()
        else: st.write("아직 제외된 지식이 없습니다.")

# --- 5. 질문 게시판 ---
elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q_d = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.subheader(f"❓ {q_d['title']}")
        if st.button(f"👍 {q_d.get('likes') or 0}", key="q_lk"):
            supabase.table("qa_board").update({"likes": (q_d.get('likes') or 0) + 1}).eq("id", q_d['id']).execute(); sync_qa_to_knowledge(q_d['id']); st.rerun()
        st.info(q_d['content'])
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_d['id']).order("created_at").execute().data
        for a in ans_d:
            if not a.get('parent_id'):
                st.markdown(f'<div class="a-card"><b>{a["author"]}</b>: {a["content"]} (👍{(a.get("likes") or 0)})</div>', unsafe_allow_html=True)
                if st.button("좋아요", key=f"al_{a['id']}"):
                    supabase.table("qa_answers").update({"likes": (a.get('likes') or 0) + 1}).eq("id", a['id']).execute(); sync_qa_to_knowledge(q_d['id']); st.rerun()
        with st.form("ans_v90"):
            at, ct = st.text_input("작성자"), st.text_area("답변")
            if st.form_submit_button("등록"):
                supabase.table("qa_answers").insert({"question_id": q_d['id'], "author": at, "content": clean_text_for_db(ct)}).execute(); sync_qa_to_knowledge(q_d['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 질문하기"):
            with st.form("q_v90"):
                cat, auth, tit, cont = st.selectbox("분류", ["기기이상", "일반"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("등록"):
                    res = supabase.table("qa_board").insert({"author": auth, "title": tit, "content": clean_text_for_db(cont), "category": cat}).execute()
                    if res.data: sync_qa_to_knowledge(res.data[0]['id']); st.rerun()
        for q_r in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**[{q_r['category']}] {q_r['title']}** (👍 {q_r.get('likes') or 0})")
            if c2.button("보기", key=f"q_{q_r['id']}"): st.session_state.selected_q_id = q_r['id']; st.rerun()

# --- 6. 미해결 과제 ---
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 동료의 지식이 필요한 질문")
    unsolved = supabase.table("unsolved_questions").select("*").eq("status", "대기중").order("created_at", desc=True).execute().data
    if not unsolved: st.success("✨ 과제가 없습니다!")
    else:
        for item in unsolved:
            with st.container():
                st.markdown(f"<div style='background:#fff1f2; padding:15px; border-radius:10px; border-left:5px solid #b91c1c; margin-bottom:10px;'><b>{item['query']}</b><br><small>사유: {item['reason']}</small></div>", unsafe_allow_html=True)
                with st.form(key=f"form_sos_{item['id']}"):
                    ans_in = st.text_area("조치법 입력")
                    if not item['is_lifestyle']:
                        c1, c2, c3 = st.columns(3)
                        s_mfr, s_mod, s_itm = c1.text_input("제조사", key=f"mfr_{item['id']}"), c2.text_input("모델명", key=f"mod_{item['id']}"), c3.text_input("측정항목", key=f"itm_{item['id']}")
                    cc1, cc2 = st.columns([0.8, 0.2])
                    if cc1.form_submit_button("✅ 등록"):
                        if ans_in:
                            f_m = s_mfr if not item['is_lifestyle'] and s_mfr else ('생활정보' if item['is_lifestyle'] else '현장장비')
                            f_mo = s_mod if not item['is_lifestyle'] and s_mod else '일반'
                            f_it = s_itm if not item['is_lifestyle'] and s_itm else '일반'
                            n_v = get_embedding(f"{f_m} {f_mo} {item['query']} {ans_in}")
                            supabase.table("knowledge_base").insert({"category": '현장꿀팁', "manufacturer": f_m, "model_name": f_mo, "measurement_item": f_it, "issue": item['query'], "solution": ans_in, "registered_by": "동료지성", "embedding": n_v}).execute()
                            supabase.table("unsolved_questions").update({"status": "해결됨"}).eq("id", item['id']).execute(); st.rerun()
                    if cc2.form_submit_button("🗑️ 삭제"): supabase.table("unsolved_questions").delete().eq("id", item['id']).execute(); st.rerun()
                st.divider()
