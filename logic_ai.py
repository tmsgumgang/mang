import re
import json
import google.generativeai as genai
import streamlit as st

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

def analyze_search_intent(ai_model, query):
    try:
        prompt = f"""사용자의 질문에서 '타겟 모델명'과 '측정 항목'을 추출해. 특히 TOC, TN, TP 등의 항목을 잘 구분해.
        질문: {query}
        응답형식(JSON): {{"target_model": "모델명", "target_item": "측정항목"}}"""
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return {"target_model": None, "target_item": None}

def rerank_results_ai(ai_model, query, results):
    if not results: return []
    candidates = []
    for r in results:
        candidates.append({
            "id": r.get('id'), "item": r.get('measurement_item'),
            "model": r.get('model_name'), "summary": (r.get('content') or r.get('solution'))[:150]
        })
    prompt = f"""질문: "{query}" 후보 지식들의 정합성을 0-100점으로 평가해 JSON 응답해. 항목 불일치 시 대폭 감점해.
    후보: {json.dumps(candidates, ensure_ascii=False)}
    응답형식: [{{"id": 1, "score": 95}}, ...]"""
    try:
        res = ai_model.generate_content(prompt)
        scores = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in scores}
        for r in results: r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True)
    except: return results

# [V160-Patch1] 문장 길이를 극도로 제한한 3줄 요약 프롬프트
def generate_3line_summary(ai_model, query, data):
    prompt = f"""질문: {query} 데이터: {data}
    현장 작업자를 위해 가장 중요한 조치 사항 3가지를 '3줄'로 요약해.
    [조건]
    1. 각 줄은 반드시 25자 이내의 단문으로 작성할 것.
    2. 불필요한 수식어(~를 확인하시고, ~를 시도하여 등)를 모두 제거할 것.
    3. '~함', '~임', '~것' 등 명사형 종결 어미를 권장함.
    예시: 1. 가스 라인 누출 확인 및 조임 / 2. 펌프 소모품 교체 및 세척 / 3. 전극 세정액 보충"""
    res = ai_model.generate_content(prompt)
    return res.text

def generate_relevant_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n고장 원인 및 정밀 해결 방안 기술 리포트를 작성해줘."
    res = ai_model.generate_content(prompt)
    return res.text
