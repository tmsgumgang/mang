import re
import json
import streamlit as st
from google import genai
from google.genai import types
from prompts import PROMPTS 

@st.cache_data(show_spinner=False)
def get_embedding(text):
    """
    [V246] 신형 라이브러리(google-genai) 호환성 강화
    - 여러 모델명 형식을 순차적으로 시도하여 성공률을 높입니다.
    - 실패 시 화면에 정확한 에러 원인을 출력합니다.
    """
    cleaned_text = clean_text_for_db(text)
    
    # 1. 텍스트가 없으면 API 호출 방지 (비용/에러 절약)
    if not cleaned_text:
        return []

    try:
        # 1. API 키 로드
        api_key = st.secrets["GEMINI_API_KEY"]
        client = genai.Client(api_key=api_key)
        
        # 2. 시도할 모델명 후보군
        candidate_models = ["text-embedding-004", "models/text-embedding-004"]
        last_error = None
        
        # 3. 순차적으로 시도
        for model_name in candidate_models:
            try:
                response = client.models.embed_content(
                    model=model_name,
                    contents=cleaned_text
                )
                
                if response.embeddings:
                    return response.embeddings[0].values
                    
            except Exception as e:
                print(f"⚠️ 모델 시도 실패 ({model_name}): {e}")
                last_error = e
                continue
        
        # 4. 모든 시도가 실패했을 경우
        error_msg = f"🚨 AI 임베딩 생성 실패.\n원인: {str(last_error)}"
        print(error_msg)
        st.error(error_msg)
        return []

    except Exception as e_fatal:
        st.error(f"시스템 치명적 오류: {str(e_fatal)}")
        return []

def semantic_split_v143(text, target_size=1200, min_size=600):
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

def clean_text_for_db(text):
    if not text: return ""
    text = text.replace("\u0000", "")
    return "".join(ch for ch in text if ch.isprintable() or ch in ['\n', '\r', '\t']).strip()

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# --------------------------------------------------------------------------------
# [V206] 자동 키워드 태깅(Auto-Tagging) 엔진
# --------------------------------------------------------------------------------
def extract_metadata_ai(ai_model, content):
    try:
        prompt = PROMPTS["extract_metadata"].format(content=content[:2000])
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

@st.cache_data(ttl=3600, show_spinner=False)
def analyze_search_intent
