import re
import json
import google.generativeai as genai
import streamlit as st

# [V156] 시맨틱 분할 알고리즘
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

# [V156 최적화] 리랭킹 후보군 정보 압축 및 판단 로직 강화
def rerank_results_ai(ai_model, query, results):
    if not results: return []
    
    # 토큰 절약을 위해 리랭킹 후보군을 핵심 정보로 압축
    candidates = []
    for r in results:
        candidates.append({
            "id": r.get('id'),
            "item": r.get('measurement_item'),
            "model": r.get('model_name'),
            "summary": (r.get('content') or r.get('solution'))[:150] # 150자로 단축
        })
    
    prompt = f"""질문: "{query}"
    후보 지식들입니다. 질문과의 기술적 정합성을 0-100점으로 평가해 JSON으로 응답해.
    항목(Item) 불일치 시 감점을 대폭 적용하고, 모델명 일치 시 가점을 부여해.
    후보: {json.dumps(candidates, ensure_ascii=False)}
    응답형식: [{{"id": 1, "score": 95}}, ...]"""
    
    try:
        res = ai_model.generate_content(prompt)
        scores = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in scores}
        for r in results:
            r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True)
    except:
        return results

def generate_3line_summary(ai_model, query, data):
    prompt = f"""질문: {query} 데이터: {data}
    위 내용을 바탕으로 현장 작업자를 위해 가장 중요한 조치 사항 3가지를 '3줄' 내외로 매우 간결하게 번호 붙여 요약해줘."""
    res = ai_model.generate_content(prompt)
    return res.text

def generate_relevant_summary(ai_model, query, data):
    prompt = f"""질문: {query} 데이터: {data}
    당신은 수질자동측정망 기술 전문가입니다. 상세한 기술 리포트를 작성해줘."""
    res = ai_model.generate_content(prompt)
    return res.text
