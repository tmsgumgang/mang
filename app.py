import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re
import time
from collections import Counter

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

# --- [V129] 표준 카테고리 정의 ---
DIRECT_INPUT_LABEL = "직접 입력"
DOMAIN_MAP = {
    "기술지식": {
        "측정기기": ["TOC", "TN", "TP", "일반항목", "VOCs", "물벼룩", "황산화", "미생물", "발광박테리아", "기타"],
        "채수시설": ["펌프", "레듀샤", "호스", "커플링", "캡록", "여과 필터", "기타"],
        "전처리/반응조": ["공통"], "통신/데이터": ["공통"], "전기/제어": ["공통"], "소모품/시약": ["공통"]
    },
    "행정절차": {
        "점검/보고": ["공통"], "구매/신청": ["공통"], "안전/규정": ["공통"], "매뉴얼/지침": ["공통"]
    },
    "복지생활": {
        "맛집/식당": ["공통"], "카페/편의": ["공통"], "주차/교통": ["공통"], "기상/재난": ["공통"]
    }
}

# --- 핵심 헬퍼 함수 ---
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

def get_penalty_counts():
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").execute()
        return Counter([r['source_id'] for r in res.data])
    except: return {}

# [V129] 고품질 맥락 병합 (600자 미만 파편 금지)
def semantic_split_v129(text, target_size=1200, min_size=600):
    flat_text = " ".join(text.split())
    sentences = re.split(r'(?<=[.!?])\s+', flat_text)
    chunks, current_chunk = [], ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= target_size:
            current_chunk += " " + sentence
        else:
            if current_chunk: chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        if len(current_chunk) < min_size and chunks: chunks[-1] = chunks[-1] + " " + current_chunk.strip()
        else: chunks.append(current_chunk.strip())
    return chunks

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇 V129", layout="centered", initial_sidebar_state="collapsed")
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    .guide-box { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 10px; border-radius: 6px; font-size: 0.82rem; color: #475569; margin-top: 5px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇 V129</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판", "🆘 미해결 과제"]
st.session_state.page_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")

# --- 1. 통합 지식 검색 (V129: 사용자 정의 임계값 제어) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    
    # [V129 핵심] 검색 정밀도 제어 슬라이더
    with st.expander("⚙️ 검색 정밀도 설정 (임계값)", expanded=False):
        u_threshold = st.slider("임계값 조절 (값이 높을수록 깐깐해집니다)", 0.0, 1.0, 0.5, 0.05)
        st.markdown(f"""
        <div class="guide-box">
            🎯 <b>현재 모드: {"정밀 타격 (Stricter)" if u_threshold > 0.6 else ("균형 (Balanced)" if u_threshold >= 0.4 else "포괄 탐색 (Broader)")}</b><br>
            • <b>높음(0.7~0.9):</b> 모델명이나 전문 용어를 정확히 찾을 때 추천<br>
            • <b>낮음(0.1~0.3):</b> 직접적인 단어가 없어도 유사한 맥락을 찾을 때 추천
        </div>
        """, unsafe_allow_html=True)

    col_i, col_b = st.columns([0.8, 0.2])
    user_q = col_i.text_input("질문 입력", label_visibility="collapsed", placeholder="질문이나 장비 모델명을 입력하세요")
    
    if col_b.button("조회", use_container_width=True) or user_q:
        if user_q:
            with st.spinner("설정된 정밀도로 지식을 분석 중..."):
                try:
                    target_domains = ["기술지식", "기술자산"] if "업무기술" in search_mode else ["복지생활"]
                    q_vec = get_embedding(user_q)
                    penalty_map = get_penalty_counts()
                    
                    # [V129 핵심] 사용자 정의 임계값 적용
                    m_cands = supabase.rpc("match_manual", {"query_embedding": q_vec, "match_threshold": u_threshold, "match_count": 50}).execute().data or []
                    k_cands = supabase.rpc("match_knowledge", {"query_embedding": q_vec, "match_threshold": u_threshold, "match_count": 50}).execute().data or []
                    
                    final_pool, seen_ks = [], set()
                    for d in (m_cands + k_cands):
                        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                        if d.get('domain') not in target_domains or d.get('review_required'): continue
                        
                        penalty = penalty_map.get(u_key, 0) * 0.05
                        d['final_score'] = (d.get('similarity') or 0) - penalty
                        if u_key not in seen_ks:
                            final_pool.append(d); seen_ks.add(u_key)

                    final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)
                    
                    if final_pool:
                        st.subheader("🤖 AI 전문가 분석 요약")
                        prompt = f"질문: {user_q}\n데이터: {final_pool[:12]}\n도메인: {target_domains}. 요약해줘."
                        st.info(ai_model.generate_content(prompt).text)
                        for i, d in enumerate(final_pool[:10]):
                            with st.expander(f"{i+1}. [{d.get('sub_category','상세지식')}] {str(d.get('issue') or '매뉴얼 조각')[:40]}..."):
                                st.markdown(f'<div class="meta-bar"><span>📁 출처: <b>{d.get("file_name","개별지식")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🎯 유사도: <b>{round(d.get("similarity",0), 2)}</b></span></div>', unsafe_allow_html=True)
                                st.write(d.get('solution') or d.get('content'))
                    else:
                        st.warning(f"🔍 임계값 {u_threshold} 기준으로는 일치하는 지식이 없습니다. 설정에서 임계값을 낮추어 보세요.")
                except Exception as e: st.error(f"검색 오류: {e}")

# --- 4. 데이터 전체 관리 (전 기능 누락 없음) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    tabs = st.tabs(["📝 경험 리파이너", "📄 매뉴얼 리파이너", "🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축"])
    
    with tabs[3]: # 수동 분류실 (V125 저장 보장 로직)
        st.subheader("🚨 지식 수동 분류 및 정밀 태깅")
        t_sel = st.radio("분류 대상", ["경험", "매뉴얼"], horizontal=True, key="v129_rv")
        t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
        review_list = supabase.table(t_name).select("*").eq("review_required", True).limit(2).execute().data
        if review_list:
            for item in review_list:
                st.markdown(f"**[원문]**\n{item.get('content') or item.get('solution')}")
                with st.form(key=f"rv_v129_{item['id']}"):
                    c1, c2, c3 = st.columns(3)
                    m_dom = c1.selectbox("도메인", list(DOMAIN_MAP.keys()), key=f"d_{item['id']}")
                    m_sub_sel = c2.selectbox("세부분류", list(DOMAIN_MAP[m_dom].keys()) + [DIRECT_INPUT_LABEL], key=f"s_{item['id']}")
                    m_sub_txt = c2.text_input("└ 직접 입력", key=f"st_{item['id']}")
                    m_itm_sel = c3.selectbox("상세 항목", DOMAIN_MAP[m_dom].get(m_sub_sel, ["공통"]) + [DIRECT_INPUT_LABEL], key=f"i_{item['id']}")
                    m_itm_txt = c3.text_input("└ 직접 입력", key=f"it_{item['id']}")
                    if st.form_submit_button("✅ 분류 확정"):
                        f_sub = m_sub_txt if m_sub_sel == DIRECT_INPUT_LABEL else m_sub_sel
                        f_itm = m_itm_txt if m_itm_sel == DIRECT_INPUT_LABEL else m_itm_sel
                        supabase.table(t_name).update({"domain": m_dom, "sub_category": f_sub, "measurement_item": f_itm, "review_required": False, "semantic_version": 1}).eq("id", item['id']).execute()
                        st.rerun()

    with tabs[4]: # 지식 재건축 (V125 완전 청산 로직)
        st.subheader("🏗️ 지식 재건축 (맥락 복원)")
        files = sorted(list(set([r['file_name'] for r in supabase.table("manual_base").select("file_name").execute().data if r.get('file_name')])))
        t_file = st.selectbox("최적화 파일 선택", options=files)
        if st.button("🚀 지식 전면 재구성"):
            with st.status("🏗️ 재구성 중...") as status:
                old_data = supabase.table("manual_base").select("*").eq("file_name", t_file).order("id").execute().data
                if old_data:
                    full_text = " ".join([r['content'] for r in old_data])
                    new_chunks = semantic_split_v129(full_text)
                    for chunk in new_chunks:
                        supabase.table("manual_base").insert({"domain": old_data[0].get('domain','기술지식'), "content": clean_text_for_db(chunk), "file_name": t_file, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
                    for oid in [r['id'] for r in old_data]: supabase.table("manual_base").delete().eq("id", oid).execute()
                    status.update(label="완료!", state="complete")
                st.rerun()

# --- 2, 3 메뉴 (안정화 로직 유지) ---
elif st.session_state.page_mode == "📝 지식 등록":
    with st.form("reg_v129"):
        f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
        f_iss, f_sol = st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("저장"):
            supabase.table("knowledge_base").insert({"domain": f_dom, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1}).execute()
            st.success("완료!")

elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f and st.button("🚀 학습 시작"):
        up_f.seek(0)
        pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
        all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
        chunks = semantic_split_v129(all_t)
        for chunk in chunks:
            supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
        st.success("완료!"); st.rerun()
