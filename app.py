import streamlit as st
import io, time
import PyPDF2
import google.generativeai as genai
from supabase import create_client
from logic_processor import *
from db_services import DBManager

# [보안] Streamlit Secrets
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_system():
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.0-flash')
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

# --- 표준 카테고리 정의 ---
DIRECT_INPUT_LABEL = "직접 입력"
DOMAIN_MAP = {
    "기술지식": {
        "측정기기": ["TOC", "TN", "TP", "일반항목", "VOCs", "물벼룩", "황산화", "미생물", "발광박테리아", "기타"],
        "채수시설": ["펌프", "레듀샤", "호스", "커플링", "캡록", "여과 필터", "기타"],
        "전처리/반응조": ["공통"], "통신/데이터": ["공통"], "전기/제어": ["공통"], "소모품/시약": ["공통"]
    },
    "행정절차": { "점검/보고": ["공통"], "구매/신청": ["공통"], "안전/규정": ["공통"], "매뉴얼/지침": ["공통"] },
    "복지생활": { "맛집/식당": ["공통"], "카페/편의": ["공통"], "주차/교통": ["공통"], "기상/재난": ["공통"] }
}

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

# --- UI Layout ---
st.set_page_config(page_title="금강수계 AI V133", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; }
    .main .block-container { padding-top: 4.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.1); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    .bulk-box { background-color: #f0f9ff; border: 1px solid #bae6fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V133</div>""", unsafe_allow_html=True)

menu = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"]
mode = st.selectbox("메뉴 선택", menu, label_visibility="collapsed")

# --- 1. 통합 검색 ---
if mode == "🔍 통합 지식 검색":
    col_l, col_r = st.columns([0.7, 0.3])
    with col_l:
        s_mode = st.radio("모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True)
        user_q = st.text_input("질문", placeholder="장비 모델명이나 궁금한 점을 입력하세요")
    with col_r:
        u_threshold = st.slider("정밀도(임계값)", 0.0, 1.0, 0.5, 0.05)
    
    if user_q:
        with st.spinner("검증된 지식 검색 중..."):
            target_doms = ["기술지식", "기술자산"] if "업무" in s_mode else ["복지생활"]
            q_vec = get_embedding(user_q)
            blacklist = db.get_blacklist_ids(user_q)
            penalties = db.get_penalty_counts()
            
            results = db.match_manual_db(q_vec, u_threshold) + db.match_knowledge_db(q_vec, u_threshold)
            final = []
            for d in results:
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if u_key not in blacklist and d.get('domain') in target_doms and not d.get('review_required') and d.get('semantic_version') == 1:
                    d['final_score'] = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.05)
                    final.append(d)
            
            final = sorted(final, key=lambda x: x['final_score'], reverse=True)
            if final:
                st.subheader("🤖 AI 정밀 답변")
                st.info(ai_model.generate_content(f"질문: {user_q} 데이터: {final[:10]}").text)
                for d in final[:5]:
                    with st.expander(f"[{d.get('model_name','공통')}] 상세 내용"):
                        st.markdown(f'<div class="meta-bar"><span>📁 출처: {d.get("file_name","개별지식")}</span><span>🧪 항목: {d.get("measurement_item","공통")}</span></div>', unsafe_allow_html=True)
                        st.write(d.get('content') or d.get('solution'))
            else: st.warning("🔍 일치하는 승인된 지식이 없습니다.")

# --- 4. 데이터 관리 (V133: 일괄 승인 UI 추가) ---
elif mode == "🛠️ 데이터 전체 관리":
    tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
    
    with tabs[3]: # [V133 핵심] 라벨 승인 및 일괄 처리
        st.subheader("🏷️ AI 라벨링 최종 검토 및 승인")
        t_sel = st.radio("테이블", ["경험", "매뉴얼"], horizontal=True, key="v133_apprv_target")
        t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
        
        # 1. 일괄 승인 섹션
        st.markdown('<div class="bulk-box">', unsafe_allow_html=True)
        st.write("📂 **파일 단위 일괄 승인**")
        # 제안 상태(version=2)인 파일 목록 추출
        all_staging = db.supabase.table(t_name).select("file_name").eq("semantic_version", 2).execute().data
        staging_files = sorted(list(set([r['file_name'] for r in all_staging if r.get('file_name')])))
        
        if staging_files:
            c1, c2 = st.columns([0.7, 0.3])
            target_f = c1.selectbox("일괄 승인할 파일 선택", options=staging_files, label_visibility="collapsed")
            if c2.button("🚀 선택 파일 전체 승인", use_container_width=True):
                if db.bulk_approve_file(t_name, target_f):
                    st.toast(f"'{target_f}' 파일의 모든 지식이 승인되었습니다!", icon="✅")
                    time.sleep(1); st.rerun()
        else:
            st.write("대기 중인 파일이 없습니다.")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 2. 개별 승인 섹션 (기존 로직 유지)
        st.write("🔍 **개별 지식 검토**")
        staging = db.supabase.table(t_name).select("*").eq("semantic_version", 2).limit(3).execute().data
        if not staging: st.success("🎉 모든 라벨링 검토 완료!")
        else:
            for r in staging:
                with st.form(key=f"apprv_{r['id']}"):
                    st.write(f"ID {r['id']}: {r.get('content') or r.get('solution')[:400]}")
                    c1, c2, c3 = st.columns(3)
                    a_mfr = c1.text_input("제조사", value=r.get('manufacturer','미지정'), key=f"mfr_{r['id']}")
                    a_mod = c2.text_input("모델명", value=r.get('model_name','공통'), key=f"mod_{r['id']}")
                    a_itm = c3.text_input("항목", value=r.get('measurement_item','공통'), key=f"itm_{r['id']}")
                    if st.form_submit_button("✅ 개별 승인"):
                        db.supabase.table(t_name).update({"manufacturer": a_mfr, "model_name": a_mod, "measurement_item": a_itm, "semantic_version": 1}).eq("id", r['id']).execute()
                        st.rerun()

# --- 3. 문서 등록 및 2. 지식 등록 (이전 로직 동일) ---
elif mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f and st.button("🚀 지능형 학습 (검수 대기)"):
        pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
        all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
        chunks = semantic_split_v132(all_t)
        for chunk in chunks:
            meta = extract_metadata_ai(ai_model, chunk)
            db.supabase.table("manual_base").insert({
                "domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name,
                "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'),
                "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2
            }).execute()
        st.success("학습 완료! '라벨 승인' 탭에서 일괄 혹은 개별 검토해 주세요."); st.rerun()

elif mode == "📝 지식 등록":
    with st.form("reg_v133"):
        f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
        f_iss, f_sol = st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("저장"):
            db.supabase.table("knowledge_base").insert({"domain": f_dom, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1}).execute()
            st.success("등록 완료!")
