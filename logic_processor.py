import re
import json
import google.generativeai as genai
import streamlit as st

# [V154] 시맨틱 분할 알고리즘 로직 유지
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

def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"""텍스트에서 정보를 정밀하게 추출해 JSON으로 응답해.
        - manufacturer: 제조사
        - model_name: 모델명
        - measurement_item: 측정항목
        텍스트: {content[:2000]}
        응답형식(JSON): {{"manufacturer": "값", "model_name": "값", "measurement_item": "값"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

def analyze_search_intent(ai_model, query):
    try:
        prompt = f"""사용자의 질문에서 '타겟 모델명'과 '측정 항목'을 추출해. 특히 TOC, TN, TP 등의 항목을 잘 구분해.
        질문: {query}
        응답형식(JSON): {{"target_model": "모델명", "target_item": "측정항목"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return {"target_model": None, "target_item": None}

# [V154] 압축된 데이터(Top 5) 기반 3줄 요약
def generate_3line_summary(ai_model, query, data):
    prompt = f"""질문: {query} 데이터: {data}
    위 내용을 바탕으로 현장 작업자를 위해 가장 중요한 조치 사항 3가지를 '3줄' 내외로 매우 간결하게 번호 붙여 요약해줘. 
    가장 핵심적인 해결책 위주로 작성할 것."""
    res = ai_model.generate_content(prompt)
    return res.text

# [V154] 요청 시에만 실행될 상세 분석 엔진
def generate_relevant_summary(ai_model, query, data):
    prompt = f"""질문: {query} 데이터: {data}
    당신은 수질자동측정망 기술 전문가입니다. 위 데이터를 바탕으로 장비 개요, 작동 원리, 고장 원인 분석 및 단계별 해결 방안을 포함한 매우 상세한 기술 리포트를 작성해줘."""
    res = ai_model.generate_content(prompt)
    return res.text
