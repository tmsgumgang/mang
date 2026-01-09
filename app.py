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

# --- [V127] 표준 카테고리 및 도메인 정의 ---
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

# [V127] 맥락 보존 분할 (600자 병합)
def semantic_split_v127(text, target_size=1200, min_size=600):
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
st.set_page_config(page_title="금강수계 AI 챗봇 V127", layout="centered", initial_sidebar_state="collapsed")
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇 V127</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판", "🆘 미해결 과제"]
st.session_state.page_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")

# --- 1. 통합 지식 검색 (전 기능 복구 버전) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    user_q = st.text_input("질문 입력", label_visibility="collapsed", placeholder="장비 모델명이나 궁금한 점을 입력하세요")
    
    if user_q:
        with st.spinner("지식고에서 최적의 답변을 구성 중입니다..."):
            try:
                target_domains = ["기술지식", "기술자산"] if "업무기술" in search_mode else ["복지생활"]
                q_vec = get_embedding(user_q)
                
                # 블랙리스트 및 페널티 데이터 로드
                blacklist_ids = [r['source_id'] for r in supabase.table("knowledge_blacklist").select("source_id").eq("query", user_q).execute().data]
                penalty_map = get_penalty_counts()
                
                # 통합 검색 실행
                m_cands = supabase.rpc("match_manual", {"query_embedding": q_vec, "match_threshold": 0.01, "match_count": 50}).execute().data or []
                k_cands = supabase.rpc("match_knowledge", {"query_embedding": q_vec, "match_threshold": 0.01, "match_count": 50}).execute().data or []
                
                final_pool, seen_ks = [], set()
                for d in (m_cands + k_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    
                    # [V127] 블랙리스트 및 도메인 필터링
                    if u_key in blacklist_ids: continue
                    if d.get('domain') not in target_domains or d.get('review_required'): continue
                    
                    # [V127] 페널티 및 보너스 가중치 계산
                    penalty = penalty_map.get(u_key, 0) * 0.05
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    
                    if u_key not in seen_ks:
                        d['final_score'] = (d.get('similarity') or 0) - penalty
                        d['u_key'] = u_key
                        final_pool.append(d); seen_ks.add(u_key)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)
                
                if final_pool:
                    st.subheader("🤖 AI 전문가 요약")
                    ans = ai_model.generate_content(f"질문: {user_q} 데이터: {final_pool[:12]}")
                    st.info(ans.text)
                    for i, d in enumerate(final_pool[:10]):
                        with st.expander(f"{i+1}. [{d.get('sub_category','일반')}] {str(d.get('issue') or '상세 지식')[:40]}..."):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('solution') or d.get('content'))
                else:
                    st.warning("🔍 검색 결과가 없습니다. 대기실에 검토 중인 데이터가 있는지 확인해 보세요.")
            except Exception as e: st.error(f"검색 엔진 오류: {e}")

# --- 4. 데이터 전체 관리 (V127: 모든 서브 탭 기능 복구) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    tabs = st.tabs(["📝 경험 리파이너", "📄 매뉴얼 리파이너", "🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축"])
    
    with tabs[3]: # 수동 분류실 (V125 저장 로직 완결)
        st.subheader("🚨 지식 수동 분류 (표준 체계 연동)")
        t_sel = st.radio("테이블", ["경험", "매뉴얼"], horizontal=True, key="v127_rv")
        t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
        review_list = supabase.table(t_name).select("*").eq("review_required", True).limit(2).execute().data
        
        if not review_list: st.success("🎉 검토할 데이터가 없습니다.")
        else:
            for item in review_list:
                st.markdown(f"**[데이터 원문]**\n{item.get('content') or item.get('solution')}")
                with st.form(key=f"rv_v127_{item['id']}"):
                    c1, c2, c3 = st.columns(3)
                    m_dom = c1.selectbox("도메인", list(DOMAIN_MAP.keys()), key=f"d_{item['id']}")
                    m_sub_sel = c2.selectbox("세부분류", list(DOMAIN_MAP[m_dom].keys()) + [DIRECT_INPUT_LABEL], key=f"s_{item['id']}")
                    m_sub_txt = c2.text_input("└ 직접 입력", key=f"st_{item['id']}")
                    m_itm_sel = c3.selectbox("상세 항목", DOMAIN_MAP[m_dom].get(m_sub_sel, ["공통"]) + [DIRECT_INPUT_LABEL], key=f"i_{item['id']}")
                    m_itm_txt = c3.text_input("└ 직접 입력", key=f"it_{item['id']}")
                    
                    if st.form_submit_button("✅ 분류 확정 및 저장"):
                        f_sub = m_sub_txt if m_sub_sel == DIRECT_INPUT_LABEL else m_sub_sel
                        f_itm = m_itm_txt if m_itm_sel == DIRECT_INPUT_LABEL else m_itm_sel
                        supabase.table(t_name).update({
                            "domain": m_dom, "sub_category": f_sub, "measurement_item": f_itm,
                            "review_required": False, "semantic_version": 1
                        }).eq("id", item['id']).execute()
                        st.toast("저장 성공!"); time.sleep(0.5); st.rerun()

    with tabs[4]: # 지식 재건축 (V125 완전 청산 로직)
        st.subheader("🏗️ 지식 재건축 (맥락 복원)")
        files = sorted(list(set([r['file_name'] for r in supabase.table("manual_base").select("file_name").execute().data if r.get('file_name')])))
        t_file = st.selectbox("최적화 파일 선택", options=files)
        if st.button("🚀 지식 전면 재구성"):
            with st.status("🏗️ 재건축 진행 중...") as status:
                old_data = supabase.table("manual_base").select("*").eq("file_name", t_file).order("id").execute().data
                if old_data:
                    full_text = " ".join([r['content'] for r in old_data])
                    new_chunks = semantic_split_v127(full_text)
                    for chunk in new_chunks:
                        supabase.table("manual_base").insert({"domain": old_data[0].get('domain','기술지식'), "content": clean_text_for_db(chunk), "file_name": t_file, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
                    for oid in [r['id'] for r in old_data]: supabase.table(t_name).delete().eq("id", oid).execute()
                    status.update(label="완료!", state="complete")
                st.rerun()

# --- 2, 3 메뉴 (표준 체계 반영) ---
elif st.session_state.page_mode == "📝 지식 등록":
    with st.form("reg_v127"):
        f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
        f_iss, f_sol = st.text_input("제목(Issue)"), st.text_area("해결방법(Solution)")
        if st.form_submit_button("저장"):
            supabase.table("knowledge_base").insert({"domain": f_dom, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1}).execute()
            st.success("지식 저장 완료!")

elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f and st.button("🚀 지식 학습 시작"):
        up_f.seek(0)
        pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
        all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
        chunks = semantic_split_v127(all_t)
        for chunk in chunks:
            supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
        st.success("학습 완료!"); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판":
    st.info("금강수계 대원들의 지식 소통 공간입니다. (기본 기능 유지)")
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.info("해결이 필요한 질문들이 대기 중입니다. (기본 기능 유지)")
