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

# [V103] 한글 태그 명칭 정규화
def display_tag_v103(u_key, category):
    prefix = "경험지식" if "EXP_" in u_key else "매뉴얼"
    # 카테고리 이모지 추가
    icon = "🛠️" if category == "측정기기" else ("🌊" if category == "채수펌프" else "🍴")
    return f"{icon} {prefix}_{u_key.split('_')[1]} ({category})"

# [V103] 질문 분석 시 카테고리 우선 추출
def analyze_query_v103(text):
    if not text: return "측정기기", None, None, None
    # 1. 일상
    if any(k in text for k in ["맛집", "식당", "카페", "추천", "주차", "점심", "저녁"]):
        return "일상", None, None, None
    # 2. 채수펌프
    if any(k in text for k in ["펌프", "채수", "배관", "토출", "흡입", "볼륨"]):
        return "채수펌프", None, None, None
    # 3. 측정기기 세부 분석
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    item_keys = ["TOC", "TN", "TP", "VOC", "PH", "DO", "TUR", "EC"]
    found_item = next((k for k in item_keys if k.lower() in text.lower()), None)
    m_match = re.search(r'(\d{2,})', text)
    found_mod = m_match.group(1) if m_match else None
    return "측정기기", found_mfr, found_mod, found_item

# 블랙리스트 사유 저장
def add_to_blacklist(query, source_id, reason):
    try: supabase.table("knowledge_blacklist").insert({"query": query, "source_id": source_id, "reason": reason}).execute()
    except: pass
    return True

def get_blacklist(query):
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
        return [r['source_id'] for r in res.data]
    except: return []

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

# --- 1. 통합 지식 검색 (V103: 전수 카테고리 필터) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("지식 분류 및 필터링 중..."):
            try:
                target_cat, t_mfr, t_mod, t_item = analyze_query_v103(user_q)
                if "생활정보" in search_mode: target_cat = "일상"
                
                query_vec = get_embedding(user_q)
                blacklist_ids = get_blacklist(user_q)
                
                # 검색 요청
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 50}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 30}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()

                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if u_key in blacklist_ids: continue
                    
                    # [V103] 데이터의 카테고리 정보 가져오기
                    d_cat = str(d.get('category') or '측정기기')
                    # 노하우의 경우 '일상(맛집/정보)' 형식을 '일상'으로 통일
                    if "일상" in d_cat: d_cat = "일상"
                    
                    # [V103 핵심] 카테고리 필터 (불일치 시 검색 제외)
                    if target_cat != d_cat: continue
                    
                    # 세부 항목 가중치
                    bonus = 0
                    if target_cat == "측정기기":
                        if t_mfr and t_mfr.upper() in str(d.get('manufacturer') or '').upper(): bonus += 0.4
                        if t_item and t_item.upper() in str(d.get('measurement_item') or '').upper(): bonus += 0.4
                    
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    if u_key not in seen_ks and f_print not in seen_fps:
                        d['final_score'] = (d.get('similarity') or 0) + bonus + ((d.get('helpful_count') or 0) * 0.01)
                        d['source_id_tag'] = u_key
                        d['confirmed_cat'] = d_cat
                        final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)

                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    context = "\n".join([f"[{display_tag_v103(d['source_id_tag'], d['confirmed_cat'])}]: {d.get('solution') or d.get('content')}" for d in final_pool[:10]])
                    ans_p = f"수질 전문가 답변. 카테고리: {target_cat}. 질문: {user_q} \n 데이터: {context} \n 요약 후 출처 표기."
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    st.markdown("---")
                    st.caption(f"🔍 '{target_cat}' 카테고리 참조 리스트")
                    for i, d in enumerate(final_pool[:10]):
                        s_tag, d_tag = d['source_id_tag'], display_tag_v103(d['source_id_tag'], d['confirmed_cat'])
                        with st.expander(f"{i+1}. [{d_tag}] {str(d.get('issue') or '매뉴얼 조각')[:35]}..."):
                            if d.get('issue'):
                                st.markdown(f"**🚩 현상**: {d['issue']}")
                                st.markdown(f"**🛠️ 조치**: {d['solution']}")
                            else: st.markdown(f"**📄 상세내용**\n{d['content']}")
                            
                            c1, c2 = st.columns(2)
                            if c1.button("👍 도움됨", key=f"ok_{s_tag}_{i}", use_container_width=True):
                                supabase.rpc("increment_helpful", {"row_id": int(s_tag.split('_')[1]), "is_exp": "EXP" in s_tag}).execute()
                                st.success("피드백 반영!"); time.sleep(0.5); st.rerun()
                            with c2:
                                with st.popover("❌ 무관함", use_container_width=True):
                                    r_sel = st.selectbox("사유", ["카테고리 오분류", "기기 불일치", "오류 정보"], key=f"rs_{s_tag}_{i}")
                                    if st.button("확정", key=f"cf_{s_tag}_{i}"):
                                        if add_to_blacklist(user_q, s_tag, r_sel): st.error("제외됨"); time.sleep(0.5); st.rerun()
                else:
                    st.warning(f"⚠️ '{target_cat}' 분류에서 일치하는 지식을 찾지 못했습니다.")
                    log_unsolved(user_q, "카테고리 필터링 결과 없음", "일상" in target_cat)
            except Exception as e: st.error(f"조회 실패 (V103): {e}")

# --- 2. 현장 노하우 등록 (V103: 카테고리 필수 선택) ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("reg_v103", clear_on_submit=True):
        cat_sel = st.selectbox("지식 카테고리", ["측정기기", "채수펌프", "일상(맛집/정보)"])
        c1, c2 = st.columns(2)
        if "일상" not in cat_sel:
            m_sel = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            m_man = c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목 (TOC, TN 등)")
        else:
            res_n, res_l = c1.text_input("상호명/정보명"), c2.text_input("위치/지역")
        
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("상황/현상 (제목)"), st.text_area("조치/상세 내용")
        if st.form_submit_button("✅ 지식 저장"):
            final_m = (m_man if m_sel == "직접 입력" else m_sel) if "일상" not in cat_sel else "생활정보"
            final_mod = model_n if "일상" not in cat_sel else res_l
            final_it = item_n if "일상" not in cat_sel else ""
            if iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": final_m, "model_name": final_mod, "measurement_item": final_it, "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": reg_n, "embedding": get_embedding(f"{cat_sel} {final_m} {final_it} {iss_t} {sol_d}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서 등록 (V103: 문서별 카테고리 지정) ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        # 업로드 시 카테고리 미리 선택
        doc_cat = st.selectbox("문서 분류", ["측정기기", "채수펌프", "일상"])
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("기기 정보 분석 중..."):
                up_f.seek(0)
                pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_r.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"추출: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        
        c1, c2 = st.columns(2)
        f_mfr, f_mod = st.text_input("🏢 제조사", value=st.session_state.s_m), st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        
        if st.button("🚀 지식 학습 시작"):
            up_f.seek(0)
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                # [V103 핵심] 저장 시 카테고리 정보 함께 저장
                supabase.table("manual_base").insert({
                    "category": doc_cat, "manufacturer": f_mfr, "model_name": f_mod, 
                    "content": clean_text_for_db(chunk), "file_name": up_f.name, 
                    "embedding": get_embedding(chunk)
                }).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("✅ 학습 완료!"); st.rerun()

# --- 4, 5, 6 메뉴 (관리 로직 유지) ---
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
    st.subheader("💬 소통 공간") # 이전 로직과 동일

elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 해결이 필요한 질문") # 이전 로직과 동일
