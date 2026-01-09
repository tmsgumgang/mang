import re
import json
import google.generativeai as genai
import streamlit as st

def semantic_split_v137(text, target_size=1200, min_size=600):
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

def clean_text_for_db(text):
    if not text: return ""
    text = text.replace("\u0000", "")
    return "".join(ch for ch in text if ch.isprintable() or ch in ['\n', '\r', '\t']).strip()

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# [V137] AI 상관성 평가 및 요약 엔진
def generate_relevant_summary(ai_model, query, data):
    prompt = f"""너는 금강수계 수질자동측정망 기술 전문가야. 
    사용자 질문: {query}
    
    [지침]
    1. 제공된 데이터 중 질문과 '상관없는' 정보는 과감히 제외해.
    2. 데이터에 질문에 대한 직접적인 답이 없다면 억지로 꾸며내지 말고 모른다고 답해.
    3. TN-2060 등 특정 모델명 언급 시 해당 모델의 데이터만 최우선으로 분석해.
    
    데이터셋: {data}"""
    res = ai_model.generate_content(prompt)
    return res.text

def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"장비 정보 추출 JSON: {content[:1500]}\n응답: {{\"manufacturer\": \"값\", \"model_name\": \"값\", \"measurement_item\": \"값\"}}"
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None
