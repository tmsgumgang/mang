import re
import json
import google.generativeai as genai
import streamlit as st

# [V141] 맥락 보존 분할 (600자 병합)
def semantic_split_v141(text, target_size=1200, min_size=600):
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

# AI 심층 라벨 추출 (제조사, 모델, 항목)
def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"""너는 수질데이터 분류 전문가야. 텍스트에서 정보를 정밀 추출해.
        - manufacturer: 제조사 (시마즈, 백년기술, 코비, 한뫼 등)
        - model_name: 정확한 모델명 (TN-2060, TOC-4200, HATA-4000 등)
        - measurement_item: 측정항목 (TOC, TN, TP, VOCs, pH 등)
        텍스트: {content[:2000]}
        응답형식(JSON): {{"manufacturer": "값", "model_name": "값", "measurement_item": "값"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

# [V141] 검색 의도 분석 (모델명 추출)
def analyze_search_intent(ai_model, query):
    try:
        prompt = f"""사용자 질문에서 핵심 타겟 장비 정보를 추출해. 
        질문: {query}
        응답형식(JSON): {{"target_model": "모델명", "target_item": "측정항목"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return {"target_model": None, "target_item": None}

# [V141] 지능형 요약 (질문과 무관한 정보 배제)
def generate_relevant_summary(ai_model, query, data):
    prompt = f"""사용자 질문: {query}
    검색된 데이터셋: {data}
    지침:
    1. 데이터 중 질문의 모델명(예: TN-2060)과 일치하지 않는 정보는 요약에서 완전히 제외해.
    2. 질문에 대한 직접적인 답이 데이터에 없으면 솔직하게 답해.
    3. 전문가다운 톤을 유지해."""
    res = ai_model.generate_content(prompt)
    return res.text
