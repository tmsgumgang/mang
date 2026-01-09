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
DOMAIN_MAP = {
    "기술지식": {
        "측정기기": ["TOC", "TN", "TP", "일반항목", "VOCs", "물벼룩", "황산화", "미생물", "발광박테리아", "기타"],
        "채수시설": ["펌프", "레듀샤", "호스", "커플링", "캡록", "여과 필터", "기타"],
        "전처리/반응조": ["공통"], "통신/데이터": ["공통"], "전기/제어": ["공통"], "소모품/시약": ["공통"]
    }
}

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

# --- UI Layout ---
st.set_page_config(page_title="금강수계 AI V138", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; }
    .main .block-container { padding-top: 5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.1); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    .verified-badge { background-color: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 12px; font-weight: bold; font-size: 0.75rem; border: 1px solid #7dd3fc; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V138</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    menu = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"]
    mode = st.selectbox("메뉴 선택", menu, label_visibility="collapsed")

st.divider()

# --- 1. 통합 검색 (V138 의도 분석 적용) ---
if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        u_threshold = st.slider("정밀도(임계값) 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: tn-2060 점검 방법", label_visibility="collapsed")
        search_btn = st.button("🔍 지능형 검색 실행", use_container_width=True)

    if user_q and (search_btn or user_q):
        with st.spinner("질문의 의도를 분석하고 관련 지식만 필터링 중..."):
            # [V138 핵심] 질문에서 타겟 모델 추출
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            
            # 필터링 검색 실행
            m_results = db.match_filtered_db("match_manual", q_vec, u_threshold, intent)
            k_results = db.match_filtered_db("match_knowledge", q_vec, u_threshold, intent)
            
            final = []
            for d in (m_results + k_results):
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if not d.get('review_required') and d.get('semantic_version') == 1:
                    score = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.08)
                    if d.get('is_verified'): score += 0.15
                    final.append({**d, 'final_score': score, 'u_key': u_key})
            
            final = sorted(final, key=lambda x: x['final_score'], reverse=True)
            
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                if final:
                    st.subheader("🤖 AI 전문가 요약")
                    st.info(generate_relevant_summary(ai_model, user_q, final[:10]))
                    for d in final[:8]:
                        v_label = '<span class="verified-badge">✅ 전문가 인증</span>' if d.get('is_verified') else ''
                        with st.expander(f"[{d.get('model_name','공통')}] 상세 내용 {v_label}"):
                            st.markdown(f'<div class="meta-bar"><span>📁 출처: {d.get("file_name","개별지식")}</span><span>🧪 항목: {d.get("measurement_item","공통")}</span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            fb_c1, fb_c2, _ = st.columns([0.15, 0.15, 0.7])
                            if fb_c1.button("👍 도움됨", key=f"up_{d['u_key']}"): st.toast("반영됨")
                            if fb_c2.button("👎 무관함", key=f"down_{d['u_key']}"):
                                if db.add_feedback(d['u_key'], user_q, is_positive=False): st.toast("제외됨", icon="⚠️")
                else: st.warning("🔍 관련성이 높은 지식을 찾지 못했습니다.")

# --- 4. 데이터 전체 관리 (지능형 라벨링 복구 포함) ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[3]: # 라벨 승인
            st.subheader("🏷️ AI 라벨링 최종 승인")
            staging = db.supabase.table("manual_base").select("*").eq("semantic_version", 2).limit(3).execute().data
            if staging:
                for r in staging:
                    with st.form(key=f"apprv_{r['id']}"):
                        st.write(f"ID {r['id']}: {r.get('content')[:300]}...")
                        c1, c2, c3 = st.columns(3)
                        a_mfr = c1.text_input("제조사", value=r.get('manufacturer','미지정'), key=f"mfr_{r['id']}")
                        a_mod = c2.text_input("모델명", value=r.get('model_name','공통'), key=f"mod_{r['id']}")
                        a_itm = c3.text_input("항목", value=r.get('measurement_item','공통'), key=f"itm_{r['id']}")
                        if st.form_submit_button("✅ 최종 승인"):
                            db.supabase.table("manual_base").update({"manufacturer": a_mfr, "model_name": a_mod, "measurement_item": a_itm, "semantic_version": 1}).eq("id", r['id']).execute()
                            st.rerun()

# --- 3. 문서 등록 (심층 라벨링 적용) ---
elif mode == "📄 문서(매뉴얼) 등록":
    _, up_col, _ = st.columns([1, 2, 1])
    with up_col:
        up_f = st.file_uploader("PDF 업로드", type=["pdf"])
        if up_f and st.button("🚀 심층 분석 및 학습 시작", use_container_width=True):
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = semantic_split_v138(all_t)
            for chunk in chunks:
                # [V138 핵심] 조각마다 AI가 메타데이터(모델명 등) 정밀 추출
                meta = extract_metadata_ai(ai_model, chunk)
                db.supabase.table("manual_base").insert({
                    "domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name,
                    "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'),
                    "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2
                }).execute()
            st.success("심층 학습 완료! '라벨 승인' 탭에서 최종 확인하세요."); st.rerun()
