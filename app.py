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

# [V67] 장비 정보 정밀 추출 (오답 필터링 핵심)
def parse_device_info_v67(text):
    mfr_map = {
        "시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI",
        "robochem": "백년기술", "로보켐": "백년기술", "hatox": "코비", "hata": "코비", "hatn": "코비", "toc-l": "시마즈"
    }
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    # 모델명 대문자 하이픈 조합 추출 (HATOX-2000 등)
    model_match = re.search(r'[A-Z0-9]{2,}-\d{4}[A-Z]*', text.upper())
    return found_mfr, model_match.group() if model_match else None

# 게시판 지식 동기화
def sync_qa_to_knowledge(q_id):
    try:
        q_data = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        a_data = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{'답글' if a.get('parent_id') else '조치법'}] {a['author']}: {a['content']}" for a in a_data]
        full_sync_txt = f"현상: {q_data['content']}\n동료들의 해결노하우:\n" + "\n".join(ans_list)
        mfr, model = parse_device_info_v67(q_data['title'] + q_data['content'])
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "게시판답변", "manufacturer": mfr if mfr else "커뮤니티",
            "model_name": model if model else q_data['category'], "issue": q_data['title'],
            "solution": full_sync_txt, "registered_by": q_data['author'],
            "embedding": get_embedding(f"{mfr} {model} {q_data['title']} {full_sync_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 및 CSS ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"
if 'reply_target_id' not in st.session_state: st.session_state.reply_target_id = None

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

# --- 1. 통합 지식 검색 (V67: 하드 브랜드 잠금 적용) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: HATOX-2000 노하우")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("3트랙 정밀 브랜드 잠금 가동 중..."):
            try:
                target_mfr, target_model = parse_device_info_v67(user_q)
                query_vec = get_embedding(user_q)
                # 정밀도 향상을 위해 임계값 0.1로 상향
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.1, "match_count": 40}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.1, "match_count": 30}).execute().data or []
                
                t1_exp, t2_man, t3_qa = [], [], []

                # [V67 핵심] 물리적 브랜드 오염 차단 필터
                for d in exp_cands:
                    is_qa = d.get('qa_id') is not None
                    # 질문의 브랜드가 있다면, DB 제조사와 일치하지 않는 정보는 삭제
                    mfr_match = (not target_mfr) or (target_mfr in d['manufacturer'])
                    
                    if is_qa: # Track 3: 게시판 (브랜드 일치 혹은 '커뮤니티' 라벨만 허용)
                        if mfr_match or d['manufacturer'] == "커뮤니티": t3_qa.append(d)
                    elif mfr_match: # Track 1: 현장경험 (브랜드 엄격 일치)
                        t1_exp.append(d)

                for d in man_cands: # Track 2: 매뉴얼 (브랜드 일치 혹은 '기타' 라벨만 허용)
                    if (not target_mfr) or (target_mfr in d['manufacturer']) or (d['manufacturer'] == "기타"):
                        t2_man.append(d)

                final_results = t3_qa[:5] + t1_exp[:5] + t2_man[:5]
                
                if final_results:
                    context = ""
                    for d in final_results:
                        src = "게시판답변" if d.get('qa_id') else ("매뉴얼" if 'content' in d else "현장경험")
                        context += f"[{src}/{d['manufacturer']}]: {d.get('solution', d.get('content'))}\n"
                    
                    ans_p = f"""수질 장비 전문가입니다. 
                    1. 질문의 장비({target_mfr if target_mfr else '전체'})와 일치하지 않는 브랜드 조치법은 절대 언급하지 마세요.
                    2. 게시판 해결책이 있다면 이를 정답 1순위로 사용하세요.
                    3. 데이터가 부족하면 솔직히 모른다고 하세요. 3줄 요약 답변.
                    데이터: {context} \n 질문: {user_q}"""
                    st.info(ai_model.generate_content(ans_p).text)
                    st.markdown("---")
                    for d in final_results:
                        is_q, is_m = d.get('qa_id') is not None, 'content' in d
                        tag_cls = "tag-qa" if is_q else ("tag-man" if is_m else "tag-exp")
                        tag_name = "게시판답변" if is_q else ("매뉴얼" if is_m else "현장경험")
                        with st.expander(f"[{tag_name}] {d['manufacturer']} | {d['model_name']}"):
                            st.write(d.get('solution', d.get('content')))
                else: st.warning("⚠️ 정확히 일치하는 브랜드를 찾지 못했습니다.")
            except Exception as e: st.error(f"조회 실패: {e}")

# --- 2. 현장 노하우 등록 (분류별 UI 분기 적용) ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("등록 분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    
    with st.form("exp_reg_v67", clear_on_submit=True):
        if cat_sel in ["기기점검", "현장꿀팁"]:
            c1, c2 = st.columns(2)
            with c1:
                m_choice = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
                m_input = st.text_input("└ 직접 입력 시")
            with c2:
                model_n, item_n = st.text_input("모델명"), st.text_input("측정항목")
            reg_n, iss_t, sol_d = st.text_input("등록자 성함"), st.text_input("현상 (제목)"), st.text_area("조치 내용 (상세)")
        else:
            # 맛집 정보 전용 UI
            st.success("🍴 주변 맛집 정보를 공유해주세요!")
            c1, c2 = st.columns(2)
            res_n, res_l = c1.text_input("식당/장소 이름"), c2.text_input("위치 (지역/주소)")
            res_m = st.text_input("대표 메뉴/분류")
            reg_n, iss_t, sol_d = st.text_input("등록자 성함"), st.text_input("정보 요약 (제목)"), st.text_area("상세 정보 (내용)")

        if st.form_submit_button("✅ 저장"):
            if cat_sel in ["기기점검", "현장꿀팁"]:
                final_m, final_mod, final_it = (m_input if m_choice == "직접 입력" else m_choice), model_n, item_n
            else:
                final_m, final_mod, final_it = res_n, res_l, res_m
            
            if final_m and iss_t and sol_d:
                supabase.table("knowledge_base").insert({
                    "category": cat_sel, "manufacturer": clean_text_for_db(final_m),
                    "model_name": clean_text_for_db(final_mod), "measurement_item": clean_text_for_db(final_it),
                    "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d),
                    "registered_by": clean_text_for_db(reg_n),
                    "embedding": get_embedding(f"{cat_sel} {final_m} {final_mod} {iss_t} {sol_d}")
                }).execute()
                st.success("🎉 성공적으로 등록되었습니다!")

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
        f_mfr, f_model = c1.text_input("🏢 제조사", value=st.session_state.s_m), c2.text_input("🏷️ 모델명", value=st.session_state.s_mod)
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
    if st.button("🔄 게시판 지식 재동기화 (브랜드 잠금 최적화)"):
        qa_list = supabase.table("qa_board").select("id").execute().data
        for qa in qa_list: sync_qa_to_knowledge(qa['id'])
        st.success("✅ 완료!")
    t1, t2 = st.tabs(["📝 경험/맛집", "📄 매뉴얼"])
    with t1:
        ms = st.text_input("🔍 경험 검색")
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
        for a in supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute().data:
            if not a.get('parent_id'):
                st.markdown(f'<div class="a-card"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
                if st.button(f"👍 {a.get('likes', 0)}", key=f"al_{a['id']}"):
                    supabase.table("qa_answers").update({"likes": a.get('likes', 0) + 1}).eq("id", a['id']).execute(); sync_qa_to_knowledge(q['id']); st.rerun()
                for r in [x for x in supabase.table("qa_answers").select("*").eq("question_id", q['id']).execute().data if x.get('parent_id') == a['id']]:
                    st.markdown(f'<div style="margin-left: 30px; font-size: 0.9rem;">↳ <b>{r["author"]}</b>: {r["content"]}</div>', unsafe_allow_html=True)
        st.write("---")
        with st.form("new_ans_v67"):
            auth, cont = st.text_input("작성자"), st.text_area("답변 내용")
            if st.form_submit_button("등록"):
                supabase.table("qa_answers").insert({"question_id": q['id'], "author": auth, "content": clean_text_for_db(cont)}).execute()
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
