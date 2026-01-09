import re
import json
import google.generativeai as genai
import streamlit as st

# [V134] 고밀도 맥락 보존 분할 (600자 병합 유지)
def semantic_split_v134(text, target_size=1200, min_size=600):
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

def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"""텍스트에서 장비 정보를 추출해 JSON 응답해.
        - manufacturer: 제조사 명칭
        - model_name: 모델명 (예: TN-2060)
        - measurement_item: 측정항목 (TN, TOC 등)
        내용: {content[:1500]}
        응답형식: {{"manufacturer": "값", "model_name": "값", "measurement_item": "값"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

def route_intent_ai(ai_model, query):
    try:
        prompt = f"질문 도메인 판단 [기술지식, 행정절차, 복지생활]. 질문: {query}\nJSON: {{\"domain\": \"도메인\"}}"
        res = ai_model.generate_content(prompt)
        return extract_json(res.text).get('domain', '기술지식')
    except: return "기술지식"
