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

# --- [V124] 표준 카테고리 정의 (고정) ---
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

# [V124] 고품질 맥락 보존 분할 (병합 기준 500자로 대폭 강화)
def semantic_split_v124(text, target_size=1000, min_size=500):
    # 마침표, 물음표, 느낌표 뒤에 공백이 오는 지점을 쪼개기
    sentences = re.split(r'(?<=[.!?])\s+', text.replace('\n', ' ').strip())
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= target_size:
            current_chunk += " " + sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence
            
    # [V124 핵심] 마지막 자투리 강제 병합 로직
    if current_chunk:
        if len(current_chunk) < min_size and chunks:
            # 500자 미만의 파편은 무조건 이전 조각에 합침 (image_ff5aa9 현상 차단)
            chunks[-1] = chunks[-1] + " " + current_chunk.strip()
        else:
            chunks.append(current_chunk.strip())
            
    return chunks

def v124_route_intent(query):
    try:
        prompt = f"질문 도메인 판단. [기술지식, 행정절차, 복지생활] 중 하나. 질문: {query}\nJSON: {{\"domain\": \"도메인\"}}"
        res = ai_model.generate_content(prompt)
        return extract_json(res.text).get('domain', '기술지식')
    except: return "기술지식"

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇 V124", layout="centered", initial_sidebar_state="collapsed")
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇 V124</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판", "🆘 미해결 과제"]
st.session_state.page_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")

# --- 1. 통합 지식 검색 ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    user_q = col_i.text_input("질문 입력", label_visibility="collapsed", placeholder="장비 문제나 맛집을 입력하세요")
    if col_b.button("조회", use_container_width=True) or (user_q and len(user_q) > 1):
        if user_q:
            with st.spinner("전문 지식을 필터링 중..."):
                target_domain = "복지생활" if "생활정보" in search_mode else "기술지식"
                query_vec = get_embedding(user_q)
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 50}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 40}).execute().data or []
                
                final_pool, seen_ks = [], set()
                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if (d.get('domain') == target_domain or d.get('domain') == "기술자산") and u_key not in seen_ks:
                        final_pool.append(d); seen_ks.add(u_key)

                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    ans_res = ai_model.generate_content(f"질문: {user_q} 데이터: {final_pool[:8]}")
                    st.info(ans_res.text)
                    for i, d in enumerate(final_pool[:10]):
                        with st.expander(f"{i+1}. [{d.get('sub_category','일반')}] {str(d.get('issue') or '매뉴얼 조각')[:40]}..."):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('solution') or d.get('content'))
                else: st.warning("지식을 찾지 못했습니다.")

# --- 4. 데이터 전체 관리 ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    tabs = st.tabs(["📝 경험 리파이너", "📄 매뉴얼 리파이너", "🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축"])
    
    with tabs[3]: # [V124] 수동 분류실 (저장 로직 완결)
        st.subheader("🚨 지식 수동 분류 (저장 기능 보강)")
        t_sel = st.radio("분류 대상", ["경험", "매뉴얼"], horizontal=True, key="rv_v124")
        t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
        review_list = supabase.table(t_name).select("*").eq("review_required", True).limit(3).execute().data
        
        if not review_list: st.success("🎉 모든 데이터가 분류되었습니다!")
        else:
            for item in review_list:
                with st.container():
                    st.markdown(f"**[데이터 원문]**\n{item.get('content') or item.get('solution')}")
                    # [V124 핵심] 저장 실패 방지를 위한 폼 구성
                    with st.form(key=f"rv_form_v124_{item['id']}"):
                        c1, c2, c3 = st.columns(3)
                        # 1. 도메인
                        m_dom = c1.selectbox("도메인", list(DOMAIN_MAP.keys()), key=f"dom_{item['id']}")
                        # 2. 세부분류 (연동형)
                        sub_cats = list(DOMAIN_MAP[m_dom].keys()) + [DIRECT_INPUT_LABEL]
                        m_sub_sel = c2.selectbox("세부분류", sub_cats, key=f"sub_sel_{item['id']}")
                        m_manual_sub = c2.text_input("└ 세부분류 직접 작성", key=f"sub_txt_{item['id']}") if m_sub_sel == DIRECT_INPUT_LABEL else ""
                        # 3. 상세 항목 (연동형)
                        items_list = DOMAIN_MAP[m_dom].get(m_sub_sel, ["공통"]) if m_sub_sel != DIRECT_INPUT_LABEL else ["공통"]
                        m_item_sel = c3.selectbox("상세 항목/부품", items_list + [DIRECT_INPUT_LABEL], key=f"itm_sel_{item['id']}")
                        m_manual_itm = c3.text_input("└ 항목 직접 작성", key=f"itm_txt_{item['id']}") if m_item_sel == DIRECT_INPUT_LABEL else ""
                        
                        if st.form_submit_button("✅ 분류 확정 및 저장"):
                            # [V124 로직] 직접 입력창의 값을 최종적으로 낚아채기
                            final_sub = m_manual_sub if m_sub_sel == DIRECT_INPUT_LABEL else m_sub_sel
                            final_itm = m_manual_itm if m_item_sel == DIRECT_INPUT_LABEL else m_item_sel
                            
                            if not final_sub: final_sub = "일반"
                            
                            # DB 업데이트
                            try:
                                supabase.table(t_name).update({
                                    "domain": m_dom,
                                    "sub_category": final_sub,
                                    "measurement_item": final_itm,
                                    "review_required": False,
                                    "semantic_version": 1
                                }).eq("id", item['id']).execute()
                                st.toast(f"ID {item['id']} 저장 완료!", icon="✅")
                                time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"저장 실패: {e}")

    with tabs[4]: # [V124] 지식 재건축 (파편 병합 500자 기준 강화)
        st.subheader("🏗️ 매뉴얼 지식 재건축 (맥락 완결 모드)")
        files = list(set([r['file_name'] for r in supabase.table("manual_base").select("file_name").execute().data if r.get('file_name')]))
        t_file = st.selectbox("최적화 대상 파일 선택", options=files)
        if st.button("🚀 문맥 복원 재구성 (500자 미만 병합)"):
            with st.status(f"🏗️ {t_file} 고품질 재구성 중...", expanded=True) as status:
                old_rows = supabase.table("manual_base").select("*").eq("file_name", t_file).order("id").execute().data
                if old_rows:
                    full_text = " ".join([r['content'] for r in old_rows])
                    new_chunks = semantic_split_v124(full_text) # V124 강화 로직 적용
                    st.write(f"🔄 {len(old_rows)}개 파편 → {len(new_chunks)}개 고밀도 문장 덩어리로 압축")
                    
                    for chunk in new_chunks:
                        supabase.table("manual_base").insert({
                            "domain": old_rows[0].get('domain', '기술지식'),
                            "manufacturer": old_rows[0].get('manufacturer'),
                            "model_name": old_rows[0].get('model_name'),
                            "content": clean_text_for_db(chunk),
                            "file_name": t_file,
                            "embedding": get_embedding(chunk),
                            "semantic_version": 1
                        }).execute()
                    
                    # 기존 파편 일괄 삭제
                    for oid in [r['id'] for r in old_rows]: supabase.table("manual_base").delete().eq("id", oid).execute()
                    status.update(label="지식 재건축 완료!", state="complete")
                    st.success("이제 파편 없는 선명한 지식으로 검색됩니다.")
                    time.sleep(1); st.rerun()

# --- 2. 지식 등록 ---
elif st.session_state.page_mode == "📝 지식 등록":
    with st.form("reg_v124"):
        f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
        f_mfr, f_iss, f_sol = st.text_input("제조사"), st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("저장"):
            supabase.table("knowledge_base").insert({"domain": f_dom, "manufacturer": f_mfr, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1}).execute()
            st.success("완료!")

# --- 3. 문서 등록 ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
        if st.button("🚀 지식 학습 시작 (500자 병합 적용)"):
            up_f.seek(0)
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = semantic_split_v124(all_t)
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"domain": f_dom, "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("학습 완료!"); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판":
    st.subheader("💬 소통 공간")
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 해결이 필요한 질문")
