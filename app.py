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

# --- [V125] 표준 카테고리 정의 ---
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

# [V125] 초강력 맥락 병합 로직 (800자 이하 파편 생존 불가)
def semantic_split_v125(text, target_size=1200, min_size=600):
    # 줄바꿈을 공백으로 치환하여 문장 연결성 확보
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
        if len(current_chunk) < min_size and chunks:
            chunks[-1] = chunks[-1] + " " + current_chunk.strip()
        else: chunks.append(current_chunk.strip())
    return chunks

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇 V125", layout="centered", initial_sidebar_state="collapsed")
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇 V125</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판", "🆘 미해결 과제"]
st.session_state.page_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")

# --- 4. 데이터 전체 관리 (V125: 수동 분류 및 재건축 로직 전면 수정) ---
if st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    tabs = st.tabs(["📝 경험 리파이너", "📄 매뉴얼 리파이너", "🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축"])
    
    with tabs[3]: # [V125 핵심] 수동 분류실 (저장 기능 철저 보강)
        st.subheader("🚨 지식 수동 분류 (저장 기능 완결)")
        t_sel = st.radio("테이블", ["경험", "매뉴얼"], horizontal=True, key="v125_rv_target")
        t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
        
        review_list = supabase.table(t_name).select("*").eq("review_required", True).limit(2).execute().data
        if not review_list: st.success("🎉 모든 데이터가 깨끗하게 정돈되었습니다!")
        else:
            for item in review_list:
                st.info(f"📍 데이터 ID: {item['id']}")
                st.markdown(f"**[데이터 원문]**\n{item.get('content') or item.get('solution')}")
                
                # [V125] 저장 누락 방지를 위한 고립형 폼 설계
                with st.form(key=f"strict_form_{item['id']}"):
                    c1, c2, c3 = st.columns(3)
                    m_dom = c1.selectbox("도메인", list(DOMAIN_MAP.keys()), key=f"d125_{item['id']}")
                    
                    # 세부분류
                    sub_list = list(DOMAIN_MAP[m_dom].keys()) + [DIRECT_INPUT_LABEL]
                    m_sub_sel = c2.selectbox("세부분류 선택", sub_list, key=f"s125_{item['id']}")
                    m_sub_txt = c2.text_input("└ 직접 입력 시 작성", key=f"st125_{item['id']}")
                    
                    # 상세항목
                    itm_list = DOMAIN_MAP[m_dom].get(m_sub_sel, ["공통"]) if m_sub_sel != DIRECT_INPUT_LABEL else ["공통"]
                    m_itm_sel = c3.selectbox("항목 선택", itm_list + [DIRECT_INPUT_LABEL], key=f"i125_{item['id']}")
                    m_itm_txt = c3.text_input("└ 직접 입력 시 작성", key=f"it125_{item['id']}")
                    
                    if st.form_submit_button("✅ 분류 확정 및 저장"):
                        # [V125] 값 추출 시 '직접 입력' 여부를 최우선 체크
                        final_sub = m_sub_txt if m_sub_sel == DIRECT_INPUT_LABEL else m_sub_sel
                        final_itm = m_itm_txt if m_itm_sel == DIRECT_INPUT_LABEL else m_itm_sel
                        
                        if final_sub:
                            supabase.table(t_name).update({
                                "domain": m_dom, "sub_category": final_sub, "measurement_item": final_itm,
                                "review_required": False, "semantic_version": 1
                            }).eq("id", item['id']).execute()
                            st.toast("저장 성공!", icon="🔥"); time.sleep(0.5); st.rerun()

    with tabs[4]: # [V125 핵심] 지식 재건축 (완전 청산 및 재개발)
        st.subheader("🏗️ 지식 재건축 (과거 파편 전량 제거 모드)")
        st.warning("이 기능은 선택한 파일의 모든 조각을 합친 뒤 새롭게 나눕니다. 기존 조각은 삭제됩니다.")
        files = sorted(list(set([r['file_name'] for r in supabase.table("manual_base").select("file_name").execute().data if r.get('file_name')])))
        t_file = st.selectbox("파일 선택", options=files)
        
        if st.button("🚀 전체 텍스트 병합 및 고밀도 재구성 시작"):
            with st.status(f"🏗️ {t_file} 데이터 전면 개편 중...") as status:
                # 1. 과거 파편 전수 수집
                old_data = supabase.table("manual_base").select("*").eq("file_name", t_file).order("id").execute().data
                if old_data:
                    # [V125] 파편 간의 공백을 강제로 채워 병합
                    total_text = " ".join([r['content'] for r in old_data])
                    # 2. 강화된 V125 로직으로 재분할 (600자 미만 파편 금지)
                    new_chunks = semantic_split_v125(total_text)
                    st.write(f"📝 기존 {len(old_data)}개 파편 → {len(new_chunks)}개 고밀도 지식으로 전환")
                    
                    # 3. 새로운 데이터 먼저 삽입
                    for chunk in new_chunks:
                        supabase.table("manual_base").insert({
                            "domain": old_data[0].get('domain', '기술지식'),
                            "content": clean_text_for_db(chunk), "file_name": t_file,
                            "embedding": get_embedding(chunk), "semantic_version": 1
                        }).execute()
                    
                    # 4. [중요] 과거 파편들 ID 추적하여 일괄 삭제 (청산)
                    for oid in [r['id'] for r in old_data]:
                        supabase.table("manual_base").delete().eq("id", oid).execute()
                        
                    status.update(label="지식 재건축 완료!", state="complete")
                    st.success("이제 파편 없는 '완성된 문장'들이 검색됩니다."); time.sleep(1); st.rerun()

# --- 1, 2, 3 메뉴 (안정화 로직 유지) ---
elif st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    user_q = st.text_input("질문 입력", label_visibility="collapsed", placeholder="질문을 입력하세요")
    if user_q:
        with st.spinner("지식 검색 중..."):
            target_domain = "복지생활" if "생활정보" in search_mode else "기술지식"
            q_vec = get_embedding(user_q)
            cands = supabase.rpc("match_manual", {"query_embedding": q_vec, "match_threshold": 0.01, "match_count": 30}).execute().data or []
            final = [d for d in cands if d.get('domain') == target_domain and not d.get('review_required')]
            if final:
                st.info(ai_model.generate_content(f"질문: {user_q} 데이터: {final[:10]}").text)
                for d in final[:5]:
                    with st.expander(f"[{d.get('sub_category')}] 지식 상세"):
                        st.write(d.get('content'))

elif st.session_state.page_mode == "📝 지식 등록":
    with st.form("reg_v125"):
        f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
        f_iss, f_sol = st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("저장"):
            supabase.table("knowledge_base").insert({"domain": f_dom, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1}).execute()
            st.success("완료!")

elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f and st.button("🚀 고밀도 학습 시작"):
        up_f.seek(0)
        pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
        all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
        chunks = semantic_split_v125(all_t)
        for chunk in chunks:
            supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
        st.success("완료!"); st.rerun()
