import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Streamlit Cloud 설정에서 정보를 입력해 주세요.")
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

def get_embedding(text):
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return result['embedding']

# --- [V7] 모바일 최적화 및 데이터 에디터 UI ---
st.set_page_config(
    page_title="금강수계 AI 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# 세션 상태 초기화 (페이지 네비게이션)
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = "🔍 검색"

# [CSS 주입] 상단바 고정, 하단 네비게이션 1열 강제, 에디터 스타일
st.markdown("""
    <style>
    /* 1. 최상단 고정 상단바 */
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 15px 0; text-align: center;
        font-size: 1.1rem; font-weight: 800;
        z-index: 9999; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    
    /* 2. 하단 네비게이션 (무조건 가로 1열 강제) */
    .nav-container {
        position: fixed; bottom: 0; left: 0; width: 100%;
        background-color: white;
        display: flex; flex-direction: row;
        justify-content: space-around;
        padding: 10px 0; border-top: 1px solid #e2e8f0;
        z-index: 9999;
    }
    .nav-button {
        background: none; border: none; color: #475569;
        font-size: 0.85rem; font-weight: 600;
        display: flex; flex-direction: column; align-items: center;
        cursor: pointer; width: 33%;
    }
    .active-nav { color: #004a99; }

    /* 3. 여백 조정 */
    .main .block-container {
        padding-top: 5rem !important;
        padding-bottom: 7rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* 4. 가이드 문구(Press Enter) 삭제 */
    [data-testid="InputInstructions"] { display: none !important; }

    /* 5. 카드형 UI */
    .result-card {
        background-color: #ffffff; border-radius: 15px;
        padding: 18px; border-left: 6px solid #004a99;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 15px;
    }
    .card-meta { font-size: 0.75rem; color: #7f8c8d; margin-bottom: 5px; }
    .card-title { font-size: 1rem; font-weight: 800; color: #2c3e50; margin-bottom: 8px; }
    .reg-tag { font-size: 0.75rem; color: #004a99; font-weight: 600; }
    </style>
    
    <div class="fixed-header">🌊 금강수계 수질자동측정망 AI 챗봇</div>
    """, unsafe_allow_html=True)

# --- 커스텀 하단 네비게이션 (1열 강제 가로 배치) ---
# Streamlit 버튼을 사용하여 세로 쌓임을 방지하기 위해 columns 사용하되 스타일 강제 적용
st.markdown('<div class="nav-container">', unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔍 검색", use_container_width=True): st.session_state.page_mode = "🔍 검색"
with col2:
    if st.button("📝 등록", use_container_width=True): st.session_state.page_mode = "📝 등록"
with col3:
    if st.button("🛠️ 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"
st.markdown('</div>', unsafe_allow_html=True)

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# 1. 조치법 검색
if mode == "🔍 검색":
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("현장 상황", label_visibility="collapsed", placeholder="상황 입력 (예: HATP-2000 TP mv 0)")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if (submit_button or user_question) and user_question:
        with st.spinner("금강수계 동료들의 축적된 노하우를 분석 중..."):
            try:
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                if past_cases:
                    case_context = "\n".join([f"사례: {c['manufacturer']} {c['model_name']} - 등록자: {c.get('registered_by', '공동')} - 조치: {c['solution']}" for c in past_cases])
                    prompt = f"당신은 금강수계 동료들의 지식 조수입니다. 다음 데이터를 바탕으로 질문에 짧고 명확하게 답하세요.\n\n{case_context}\n\n질문: {user_question}"
                    response = ai_model.generate_content(prompt)
                    
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    st.markdown("---")
                    st.markdown("### 📚 참조 데이터 (카드)")
                    
                    for c in past_cases:
                        reg_user = c.get('registered_by', '공동 지식')
                        st.markdown(f"""
                        <div class="result-card">
                            <div class="card-meta">{c['manufacturer']} | {c['measurement_item']} | <span class="reg-tag">👤 {reg_user}</span></div>
                            <div class="card-title">{c['model_name']}</div>
                            <div style="font-size: 0.9rem; color: #34495e;"><b>⚠️ 현상:</b> {c['issue']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        with st.expander(f"🛠️ {reg_user} 님의 상세 조치 확인"):
                            st.success(f"**해결책:** {c['solution']}")
                            st.caption(f"일치도: {c['similarity']*100:.1f}%")
                else:
                    st.warning("⚠️ 아직 등록되지 않은 사례입니다. 동료들을 위해 지식을 등록해 주세요!")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# 2. 사례 등록
elif mode == "📝 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            if mfr == "직접 입력": mfr = st.text_input("제조사명 입력")
            reg_name = st.text_input("등록자 성명", placeholder="이름을 입력하세요")
        with col_m2:
            model = st.text_input("모델명")
            item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타", "직접 입력"])
            if item == "직접 입력": item = st.text_input("측정항목명 입력")
        
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        
        if st.form_submit_button("✅ 지식 베이스 저장"):
            if mfr and model and item and iss and sol and reg_name:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg_name}")
                supabase.table("knowledge_base").insert({
                    "manufacturer": mfr, "model_name": model, "measurement_item": item,
                    "issue": iss, "solution": sol, "registered_by": reg_name, "embedding": vec
                }).execute()
                st.success(f"🎉 {reg_name} 님의 노하우가 공유되었습니다!")
            else:
                st.warning("⚠️ 모든 항목과 등록자 성명을 입력해 주세요.")

# 3. 데이터 관리 (직접 수정 기능 도입)
elif mode == "🛠️ 관리":
    st.subheader("🛠️ 지식 데이터셋 수정")
    st.caption("표의 칸을 클릭해 내용을 직접 수정할 수 있습니다. 수정 후 반드시 아래 '변경사항 저장' 버튼을 누르세요.")
    
    # 데이터 불러오기
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue, solution, registered_by").execute()
    
    if res.data:
        df = pd.DataFrame(res.data)
        
        # 엑셀처럼 수정 가능한 데이터 에디터 (ID는 수정 불가)
        edited_df = st.data_editor(
            df, 
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "solution": st.column_config.TextColumn("조치 내용", width="large")
            },
            use_container_width=True,
            num_rows="dynamic" # 삭제 기능 포함
        )
        
        # 변경 사항 감지 로직 (Streamlit 데이터 에디터의 특성상 수동 비교)
        if st.button("💾 변경사항 저장 (AI 검색 갱신 포함)"):
            with st.spinner("DB 동기화 및 AI 벡터 갱신 중..."):
                try:
                    # 1. 삭제된 행 처리
                    current_ids = edited_df['id'].tolist()
                    original_ids = df['id'].tolist()
                    deleted_ids = list(set(original_ids) - set(current_ids))
                    for d_id in deleted_ids:
                        supabase.table("knowledge_base").delete().eq("id", d_id).execute()

                    # 2. 수정된 행 처리 (단순 업데이트 및 벡터 재계산)
                    for index, row in edited_df.iterrows():
                        # 기존 데이터와 비교하여 변경된 행만 업데이트
                        orig_row = df[df['id'] == row['id']].iloc[0]
                        if not row.equals(orig_row):
                            # 벡터 재계산을 위한 텍스트 조합
                            combined_text = f"{row['manufacturer']} {row['model_name']} {row['measurement_item']} {row['issue']} {row['solution']} {row['registered_by']}"
                            new_vec = get_embedding(combined_text)
                            
                            supabase.table("knowledge_base").update({
                                "manufacturer": row['manufacturer'],
                                "model_name": row['model_name'],
                                "measurement_item": row['measurement_item'],
                                "issue": row['issue'],
                                "solution": row['solution'],
                                "registered_by": row['registered_by'],
                                "embedding": new_vec # 수정 시 벡터 자동 갱신
                            }).eq("id", row['id']).execute()
                    
                    st.success("✅ 모든 변경사항이 저장되고 AI 검색 엔진이 갱신되었습니다!")
                    st.rerun()
                except Exception as e:
                    st.error(f"저장 중 오류 발생: {e}")
    else:
        st.info("데이터가 없습니다.")
