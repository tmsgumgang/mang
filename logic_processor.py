import re
import json
import google.generativeai as genai
import streamlit as st

# [V138] 고밀도 맥락 보존 분할 (600자 병합 유지)
def semantic_split_v138(text, target_size=1200, min_size=600):
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

# [V138] AI 심층 라벨링 엔진: DB 구축 시 사용
def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"""너는 수질측정망 데이터 분류 전문가야. 아래 텍스트에서 정보를 정밀 추출해.
        - manufacturer: 제조사 (예: 백년기술, 시마즈, 코비 등)
        - model_name: 모델명 (예: TN-2060, TOC-4200 등)
        - measurement_item: 측정항목 (TOC, TN, TP, VOCs 등)
        텍스트: {content[:1500]}
        응답형식: {{"manufacturer": "값", "model_name": "값", "measurement_item": "값"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

# [V138] AI 검색 의도 분석 엔진: 검색 시 사용
def analyze_search_intent(ai_model, query):
    try:
        prompt = f"""사용자의 질문에서 '타겟 장비' 정보를 추출해.
        질문: {query}
        응답형식(JSON): {{"target_model": "모델명(없으면 null)", "target_item": "측정항목(없으면 null)"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return {"target_model": None, "target_item": None}

def generate_relevant_summary(ai_model, query, data):
    prompt = f"사용자 질문: {query}\n제공된 지식: {data}\n위 지식 중 질문과 직접 관련된 내용만 요약해줘. 관련 없는 모델 정보는 절대 포함하지 마."
    res = ai_model.generate_content(prompt)
    return res.text
