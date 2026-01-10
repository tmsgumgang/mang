import re
import json
import google.generativeai as genai
import streamlit as st

@st.cache_data(show_spinner=False)
def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

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

@st.cache_data(show_spinner=False)
def analyze_search_intent(_ai_model, query):
    try:
        prompt = f"""사용자의 질문에서 '타겟 모델명'과 '측정 항목', '제조사'를 추출해.
        질문: {query}
        응답형식(JSON): {{"target_mfr": "제조사", "target_model": "모델명", "target_item": "측정항목"}}"""
        res = _ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return {"target_mfr": None, "target_model": None, "target_item": None}

# [V173] 의도(Intent) 기반 고정밀 리랭커로 수정
def rerank_results_ai(ai_model, query, results, intent):
    if not results: return []
    candidates = []
    for r in results:
        candidates.append({
            "id": r.get('id'), 
            "manufacturer": r.get('manufacturer'),
            "item": r.get('measurement_item'),
            "model": r.get('model_name'), 
            "summary": (r.get('content') or r.get('solution'))[:200]
        })
    
    # AI에게 찾아야 할 대상을 명확히 지시
    target_info = f"찾아야 할 대상 -> 제조사: {intent.get('target_mfr')}, 모델: {intent.get('target_model')}, 항목: {intent.get('target_item')}"
    
    prompt = f"""질문: "{query}"
    {target_info}
    위 정보를 바탕으로 후보 지식들이 얼마나 정답에 가까운지 0-100점으로 평가해.
    [중요] 제조사나 모델명이 다르면 무조건 10점 미만으로 평가할 것.
    후보: {json.dumps(candidates, ensure_ascii=False)}
    응답형식: [{{"id": 1, "score": 95}}, ...]"""
    
    try:
        res = ai_model.generate_content(prompt)
        scores = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in scores}
        for r in results: 
            r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True)
    except: return results

def generate_3line_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n문장 단위로 줄바꿈하여 핵심 조치 사항 3가지를 3줄로 요약해."
    res = ai_model.generate_content(prompt)
    return res.text

def generate_relevant_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n문장 단위로 줄바꿈하여 정밀 기술 리포트를 작성해줘."
    res = ai_model.generate_content(prompt)
    return res.text
