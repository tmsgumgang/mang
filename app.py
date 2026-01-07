import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re
import time

# [보안] Streamlit Secrets 연동
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

# [V69] 질문의 의도(업무 vs 맛집) 및 브랜드/모델 정밀 분석
def analyze_intent_v69(text):
    # 1. 생활정보 키워드 감지
    life_keywords = ["맛집", "식당", "카페", "메뉴", "추천", "금산", "옥천", "영동", "청주", "대전", "주차"]
    is_lifestyle = any(k in text for k in life_keywords)
    
    # 2. 제조사/모델명 추출
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술", "hatox": "코비", "hata": "코비"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    model_match = re.search(r'([A-Z0-9]{2,})[\s-]*(\d{4}|[A-Z]+)', text.upper())
    found_model = model_match.group() if model_match else None
    
    return is_lifestyle, found_mfr, found_model

# 게시판 지식 동기화 (작성자/좋아요 포함)
def sync_qa_to_knowledge(q_id):
    try:
        q_data = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        a_data = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{'답글' if a.get('parent_id') else '조치팁'}] {a['author']} (👍{a.get('likes', 0)}): {a['content']}" for a in a_data]
        full_sync_txt = f"상황: {q_data['content']}\n동료들의 해결노하우:\n" + "\n".join(ans_list)
        is_life, mfr, model = analyze_intent_v69(q_data['title'] + q_data['content'])
        
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "맛집/정보" if is_life else "게시판답변",
            "manufacturer": mfr if mfr else ("커뮤니티" if not is_life else "생활정보"),
            "model_name": model if model else q_data['category'], "issue": q_data['title'],
            "solution": full_sync_txt, "registered_by": q_data['author'],
            "embedding": get_embedding(f"{mfr} {model} {q_data['title']} {full_sync_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 설정 및 CSS ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
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
    .q-card { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 10px; color: #1e293b; }
    .a-card { background-color: #f8fafc; border-radius: 8px; padding: 12px; margin-top: 8px; border-left: 3px solid #004a99; color: #334155; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)"]
selected_mode = st.selectbox("☰ 메뉴 이동", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V69: 의도 기반 분리 검색) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="장비 문제나 주변 맛집을 물어보세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("최적의 정보를 선별 중..."):
            try:
                is_life, target_mfr, target_model = analyze_intent_v69(user_q)
                query_vec = get_embedding(user_q)
                
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 40}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 30}).execute().data or []
                
                final_results = []
                
                if is_life:
                    # [생활 정보 모드] '맛집/정보' 카테고리만 통과
                    final_results = [d for d in exp_cands if d['category'] == "맛집/정보"]
                else:
                    # [업무 지식 모드] 맛집 정보는 원천 차단 + 브랜드/모델 필터링
                    for d in exp_cands:
                        if d['category'] == "맛집/정보": continue
                        mfr_match = (not target_mfr) or (target_mfr in d['manufacturer'])
                        model_match = target_model and (target_model.replace("-","") in d['model_name'].replace("-","").upper())
                        if mfr_match or model_match or d.get('qa_id'): final_results.append(d)
                    
                    for d in man_cands:
                        mfr_match = (not target_mfr) or (target_mfr in d['manufacturer']) or (d['manufacturer'] == "기타")
                        model_match = target_model and (target_model.replace("-","") in d['model_name'].replace("-","").upper())
                        if mfr_match or model_match: final_results.append(d)

                if final_results:
                    context = ""
                    for d in final_results:
                        src = "게시판" if d.get('qa_id') else ("매뉴얼" if 'content' in d else ("맛집" if d['category'] == "맛집/정보" else "현장경험"))
                        context += f"[{src}/{d['manufacturer']}/{d['model_name']}]: {d.get('solution', d.get('content'))}\n"
                    
                    # [V69] AI 지침 수정: 의도에 따른 답변 태도 고정
                    ans_p = f"""당신은 금강수계 도우미입니다. 
                    1. 질문의 의도가 {'생활정보' if is_life else '업무지식'}이므로 관련 없는 정보는 답변에서 완전히 제외하세요.
                    2. 업무 질문 시 동료들의 '게시판' 답변을 최우선 정답으로 제시하세요.
                    3. 브랜드나 모델이 완벽히 일치하지 않아도 맥락이 비슷하면 '참고용'으로 안내하세요. 3줄 요약.
                    데이터: {context} \n 질문: {user_q}"""
                    st.info(ai_model.generate_content(ans_p).text)
                    st.markdown("---")
                    for d in final_results:
                        is_q, is_m, is_i = d.get('qa_id'), 'content' in d, d['category'] == "맛집/정보"
                        tag_name = "게시판답변" if is_q else ("매뉴얼" if is_m else ("맛집정보" if is_i else "현장경험"))
                        with st.expander(f"[{tag_name}] {d['manufacturer']} | {d['model_name']}"):
                            st.write(d.get('solution', d.get('content')))
                else: st.warning("⚠️ 관련 정보를 찾지 못했습니다. 키워드를 바꾸어 검색해 보세요.")
            except Exception as e: st.error(f"조회 중 오류 발생: {e}")

# --- 2. 현장 노하우 등록 (UI 분기 유지) ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("등록 분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    with st.form("exp_reg_v69", clear_on_submit=True):
        if cat_sel in ["기기점검", "현장꿀팁"]:
            c1, c2 = st.columns(2)
            m_choice = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            m_input = c1.text_input("└ 직접 입력 시")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목")
            reg_n, iss_t, sol_d = st.text_input("등록자 성함"), st.text_input("현상 (제목)"), st.text_area("조치 내용")
        else:
            c1, c2 = st.columns(2)
            res_n, res_l = c1.text_input("식당/장소 이름"), c2.text_input("위치 (지역/주소)")
            res_m = st.text_input("대표 메뉴/분류")
            reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("정보 요약 (제목)"), st.text_area("상세 내용")

        if st.form_submit_button("✅ 저장"):
            final_m = (m_input if m_choice == "직접 입력" else m_choice) if cat_sel != "맛집/정보" else res_n
            final_mod, final_it = (model_n, item_n) if cat_sel != "맛집/정보" else (res_l, res_m)
            if final_m and iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": clean_text_for_db(final_m), "model_name": clean_text_for_db(final_mod), "measurement_item": clean_text_for_db(final_it), "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": clean_text_for_db(reg_n), "embedding": get_embedding(f"{cat_sel} {final_m} {final_mod} {iss_t} {sol_d}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서(매뉴얼) 등록 ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록 (768차원)")
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
        if st.button("🚀 매뉴얼 저장 시작"):
            with st.status("📑 저장 중...") as status:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                all_t = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
                chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
                pb = st.progress(0)
                for i, chunk in enumerate(chunks):
                    supabase.table("manual_base").insert({"manufacturer": f_mfr, "model_name": f_model, "content": clean_text_for_db(chunk), "file_name": up_f.name, "page_num": (i//2)+1, "embedding": get_embedding(chunk)}).execute()
                    pb.progress((i+1)/len(chunks))
                st.success("✅ 등록 완료!"); st.rerun()

# --- 4. 데이터 전체 관리 ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    if st.button("🔄 게시판 지식 재동기화 (의도 분류 보강)"):
        qa_list = supabase.table("qa_board").select("id").execute().data
        for qa in qa_list: sync_qa_to_knowledge(qa['id'])
        st.success("✅ 동기화 완료!")
    t1, t2 = st.tabs(["📝 경험/맛집 관리", "📄 매뉴얼 관리"])
    with t1:
        ms = st.text_input("🔍 경험/맛집 검색")
        if ms:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{ms}%,issue.ilike.%{ms}%,solution.ilike.%{ms}%").execute()
            for r in res.data:
                tag_cls = "tag-info" if r['category'] == "맛집/정보" else "tag-exp"
                with st.expander(f"[{r['manufacturer']}] {r['issue']}"):
                    st.markdown(f'<span class="source-tag {tag_cls}">{r["category"]}</span>', unsafe_allow_html=True)
                    st.write(r['solution'])
                    if st.button("🗑️ 삭제", key=f"e_{r['id']}"): supabase.table("knowledge_base").delete().eq("id", r['id']).execute(); st.rerun()
    with t2:
        ds = st.text_input("🔍 매뉴얼 검색")
        if ds:
            res = supabase.table("manual_base").select("*").or_(f"manufacturer.ilike.%{ds}%,content.ilike.%{ds}%,file_name.ilike.%{ds}%").execute()
            for r in res.data:
                with st.expander(f"[{r['manufacturer']}] {r['file_name']}"):
                    st.write(r['content'][:300])
                    if st.button("🗑️ 삭제", key=f"m_{r['id']}"): supabase.table("manual_base").delete().eq("id", r['id']).execute(); st.rerun()

# --- 5. 질문 게시판 ---
elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.subheader(f"❓ {q['title']}"); st.caption(f"👤 {q['author']} | 📅 {q['created_at'][:10]}")
        if st.button(f"👍 {q.get('likes', 0)}", key="q_lk"):
            supabase.table("qa_board").update({"likes": q.get('likes', 0) + 1}).eq("id", q['id']).execute(); sync_qa_to_knowledge(q['id']); st.rerun()
        st.info(q['content'])
        ans_data = supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute().data
        for a in [x for x in ans_data if not x.get('parent_id')]:
            st.markdown(f'<div class="a-card"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
            if st.button(f"👍 {a.get('likes', 0)}", key=f"al_{a['id']}"):
                supabase.table("qa_answers").update({"likes": a.get('likes', 0) + 1}).eq("id", a['id']).execute(); sync_qa_to_knowledge(q['id']); st.rerun()
            for r in [x for x in ans_data if x.get('parent_id') == a['id']]:
                st.markdown(f'<div style="margin-left: 30px; font-size: 0.9rem;">↳ <b>{r["author"]}</b>: {r["content"]}</div>', unsafe_allow_html=True)
        with st.form("new_ans_v69"):
            at, ct = st.text_input("작성자"), st.text_area("답변")
            if st.form_submit_button("등록"):
                supabase.table("qa_answers").insert({"question_id": q['id'], "author": at, "content": clean_text_for_db(ct)}).execute()
                sync_qa_to_knowledge(q['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 질문하기", use_container_width=True):
            with st.form("q_form"):
                cat, auth, tit, cont = st.selectbox("분류", ["기기이상", "일반"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("등록"):
                    res = supabase.table("qa_board").insert({"author": auth, "title": tit, "content": clean_text_for_db(cont), "category": cat}).execute()
                    if res.data: sync_qa_to_knowledge(res.data[0]['id']); st.rerun()
        for q_row in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**[{q_row['category']}] {q_row['title']}** (👍 {q_row.get('likes', 0)})\n👤 {q_row['author']} | 📅 {q_row['created_at'][:10]}")
            if c2.button("보기", key=f"q_{q_row['id']}"): st.session_state.selected_q_id = q_row['id']; st.rerun()
            st.write("---")
