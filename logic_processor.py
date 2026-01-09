import re
import json
import google.generativeai as genai
import streamlit as st

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

def generate_relevant_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n위 내용을 바탕으로 전문가용 기술 답변을 작성해줘."
    res = ai_model.generate_content(prompt)
    return res.text
