import re
import json
import google.generativeai as genai
import streamlit as st

# [V139] 고밀도 맥락 보존 분할 (600자 병합 유지)
def semantic_split_v139(text, target_size=1200, min_size=600):
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

# [V139] AI 심층 엔티티 추출 프롬프트 강화
def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"""너는 금강수계 수질데이터 정밀 분류가야. 텍스트를 정독하고 장비 정보를 '반드시' 구체적으로 추출해.
        - manufacturer: 제조사 (시마즈, 백년기술, 코비, 한뫼 등)
        - model_name: 정확한 모델명 (TN-2060, TOC-4200, HATA-4000 등)
        - measurement_item: 측정항목 (TOC, TN, TP, VOCs, pH 등)
        - 팁: 불확실해도 텍스트 내 가장 가능성 높은 명칭을 적어. '공통'은 최후의 수단이야.
        
        텍스트: {content[:2000]}
        응답형식(JSON): {{"manufacturer": "값", "model_name": "값", "measurement_item": "값"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

# [V139] 검색 의도 및 모델명 추출 엔진
def analyze_search_intent(ai_model, query):
    try:
        prompt = f"""사용자 질문에서 핵심 타겟 장비 정보를 추출해.
        질문: {query}
        응답형식(JSON): {{"target_model": "추출된 모델명", "target_item": "추출된 측정항목"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return {"target_model": None, "target_item": None}

def generate_relevant_summary(ai_model, query, data):
    prompt = f"""질문: {query}
    제공된 데이터: {data}
    지침:
    1. 질문에 등장한 모델명(예: TOC-4200)과 데이터의 모델명이 일치하는 정보만 최우선으로 요약해.
    2. 모델명이 다른 정보는 '참고용'으로만 아주 짧게 언급하거나 제외해.
    3. 데이터에 답이 없으면 억지로 만들지 마."""
    res = ai_model.generate_content(prompt)
    return res.text
