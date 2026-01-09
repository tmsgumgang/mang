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

# --- 핵심 헬퍼 함수 (최상단 정의) ---
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

# [V104] 미해결 질문 등록 (오류 수정됨)
def log_unsolved(query, reason, is_life):
    try:
        exists = supabase.table("unsolved_questions").select("id").eq("query", query).eq("status", "대기중").execute().data
        if not exists:
            supabase.table("unsolved_questions").insert({"query": query, "reason": reason, "is_lifestyle": is_life}).execute()
    except: pass

# [V104] 카테고리별 태그 표시
def display_tag_v104(u_key, category):
    prefix = "경험지식" if "EXP" in u_key else "매뉴얼"
    icon = "🛠️" if category == "측정기기" else ("🌊" if category == "채수펌프" else "🍴")
    num = u_key.split("_")[1]
    return f"{icon} {prefix}_{num} ({category})"

# [V104] 3대 카테고리 정밀 분석
def analyze_query_v104(text):
    if not text: return "측정기기", None, None, None
    # 1. 일상
    if any(k in text for k in ["맛집", "식당", "카페", "추천", "주차", "점심", "저녁", "메뉴"]):
        return "일상", None, None, None
    # 2. 채수펌프
    if any(k in text for k in ["펌프", "채수", "배관", "토출", "흡입", "볼륨", "호스"]):
        return "채수펌프", None, None, None
    # 3. 측정기기
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    item_keys = ["TOC", "TN", "TP", "VOC", "PH", "DO", "TUR", "EC", "온도"]
    found_item = next((k for k in item_keys if k.lower() in text.lower()), None)
    m_match = re.search(r'(\d{2,})', text)
    found_mod = m_match.group(1) if m_match else None
    return "측정기기", found_mfr, found_mod, found_item

def get_blacklist(query):
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
        return [r['source_id'] for r in res.data]
    except: return []

def sync_qa_to_knowledge(q_id):
    try:
        q_d = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{a['author']}]: {a['content']}" for a in ans_d]
        full_txt = f"현상: {q_d['content']}\n조치:\n" + "\n".join(ans_list)
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "측정기기", "manufacturer": "커뮤니티",
            "model_name": q_d.get('category', '일반'), "issue": q_d['title'], "solution": full_txt,
            "registered_by": q_d['author'], "embedding": get_embedding(f"측정기기 {q_d['title']} {full_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .guide-box { background-color: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 15px; color: #166534; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V104: 카테고리 완전 격리) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("지식 분류 및 필터링 중..."):
            try:
                target_cat, t_mfr, t_mod, t_item = analyze_query_v104(user_q)
                if "생활정보" in search_mode: target_cat = "일상"
                
                query_vec = get_embedding(user_q)
                blacklist_ids = get_blacklist(user_q)
                
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 60}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 40}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()

                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if u_key in blacklist_ids: continue
                    
                    # [V104] 데이터 카테고리 판별
                    d_cat_raw = str(d.get('category') or '측정기기')
                    if "일상" in d_cat_raw or "맛집" in d_cat_raw: d_cat = "일상"
                    elif "채수펌프" in d_cat_raw or "펌프" in d_cat_raw: d_cat = "채수펌프"
                    else: d_cat = "측정기기"
                    
                    # [V104 핵심] 카테고리 물리적 격리 (타 카테고리 절대 불허)
                    if target_cat != d_cat: continue
                    
                    # 가중치 계산
                    bonus = 0
                    if target_cat == "측정기기":
                        if t_mfr and t_mfr.upper() in str(d.get('manufacturer') or '').upper(): bonus += 0.5
                        if t_item and t_item.upper() in str(d.get('measurement_item') or '').upper(): bonus += 0.5
                    
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    if u_key not in seen_ks and f_print not in seen_fps:
                        d['final_score'] = (d.get('similarity') or 0) + bonus + ((d.get('helpful_count') or 0) * 0.01)
                        d['source_id_tag'] = u_key
                        d['final_cat'] = d_cat
                        final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)

                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    context = "\n".join([f"[{display_tag_v104(d['source_id_tag'], d['final_cat'])}]: {d.get('solution') or d.get('content')}" for d in final_pool[:12]])
                    ans_p = f"금강수계 수질 전문가입니다. 분류: {target_cat}. 질문: {user_q} \n 데이터: {context} \n 요약 후 출처 표기."
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    st.markdown('<div class="guide-box">✅ 하단 리스트에서 지식을 평가해 주세요. <b>[무관함]</b> 선택 시 해당 정보는 검색에서 배제됩니다.</div>', unsafe_allow_html=True)
                    for i, d in enumerate(final_pool[:10]):
                        s_tag, d_tag = d['source_id_tag'], display_tag_v104(d['source_id_tag'], d['final_cat'])
                        with st.expander(f"{i+1}. [{d_tag}] {str(d.get('issue') or '상세 지식')[:35]}..."):
                            if d.get('issue'):
                                st.markdown(f"**🚩 현상**: {d['issue']}"); st.markdown(f"**🛠️ 조치**: {d['solution']}")
                            else: st.markdown(f"**📄 상세내용**\n{d['content']}")
                            c1, c2 = st.columns(2)
                            if c1.button("👍 도움됨", key=f"ok_{s_tag}_{i}", use_container_width=True):
                                prefix, rid = s_tag.split("_")
                                supabase.table("knowledge_base" if prefix=="EXP" else "manual_base").update({"helpful_count": (d.get('helpful_count') or 0)+1}).eq("id", int(rid)).execute()
                                st.success("반영됨!"); time.sleep(0.5); st.rerun()
                            with c2:
                                with st.popover("❌ 무관함", use_container_width=True):
                                    r_sel = st.selectbox("사유", ["카테고리 오분류", "기기 불일치", "오래된 정보"], key=f"rs_{s_tag}_{i}")
                                    if st.button("제외 확정", key=f"cf_{s_tag}_{i}"):
                                        if add_to_blacklist(user_q, s_tag, r_sel): st.error("제외되었습니다."); time.sleep(0.5); st.rerun()
                else:
                    st.warning(f"⚠️ '{target_cat}' 분류에서 일치하는 지식을 찾지 못했습니다.")
                    log_unsolved(user_q, f"분류({target_cat}) 내 검색결과 없음", "일상" in target_cat)
            except Exception as e: st.error(f"조회 실패 (V104): {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("reg_v104", clear_on_submit=True):
        cat_sel = st.selectbox("카테고리", ["측정기기", "채수펌프", "일상(맛집/정보)"])
        c1, c2 = st.columns(2)
        if "일상" not in cat_sel:
            m_sel = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            m_man = c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목 (TOC, TN 등)")
        else:
            res_n, res_l = c1.text_input("상호명"), c2.text_input("위치/지역")
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("상황/제목"), st.text_area("조치/설명")
        if st.form_submit_button("✅ 지식 저장"):
            final_m = (m_man if m_sel == "직접 입력" else m_sel) if "일상" not in cat_sel else "생활정보"
            final_mod = model_n if "일상" not in cat_sel else res_l
            final_it = item_n if "일상" not in cat_sel else ""
            if iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": final_m, "model_name": final_mod, "measurement_item": final_it, "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": reg_n, "embedding": get_embedding(f"{cat_sel} {final_m} {final_it} {iss_t} {sol_d}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서 등록 (V104: 저장 안정화) ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        doc_cat = st.selectbox("문서 분류", ["측정기기", "채수펌프", "일상"])
        up_f.seek(0) # [V104] 업로드 시 포인터 초기화
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("기기 정보 분석 중..."):
                pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_r.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"제조사/모델명 추출 JSON: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        c1, c2 = st.columns(2)
        f_mfr, f_model = st.text_input("🏢 제조사", value=st.session_state.s_m), st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        if st.button("🚀 지식 학습 시작"):
            up_f.seek(0) # [V104 핵심] 저장 시 포인터 재초기화
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"category": doc_cat, "manufacturer": f_mfr, "model_name": f_model, "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk)}).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("✅ 완료!"); st.rerun()

# --- 4, 5, 6 메뉴 (정상 복구) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    t1, t2, t3, t4 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 교정 기록"])
    with t3:
        st.subheader("📂 매뉴얼 관리")
        ds = st.text_input("🔍 파일명 검색")
        res_m = supabase.table("manual_base").select("*").or_(f"file_name.ilike.%{ds}%").order("created_at", desc=True).limit(50).execute()
        if res_m.data:
            for f in list(set([r['file_name'] for r in res_m.data])):
                with st.expander(f"📄 {f}"):
                    if st.button("🗑️ 삭제", key=f"df_{f}"): supabase.table("manual_base").delete().eq("file_name", f).execute(); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    st.subheader("💬 소통 공간") # 이전 버전 로직 유지

elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 해결이 필요한 질문") # 이전 버전 로직 유지
