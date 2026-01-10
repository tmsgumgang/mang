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

# [V177] 의도 분석 결과는 1시간 동안 메모리에 캐싱
@st.cache_data(ttl=3600, show_spinner=False)
def analyze_search_intent(_ai_model, query):
    default_intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
    try:
        prompt = f"""사용자의 질문에서 '타겟 모델명', '측정 항목', '제조사'를 완벽하게 추출해.
        질문: {query}
        응답형식(JSON): {{"target_mfr": "제조사", "target_model": "모델명", "target_item": "측정항목"}}"""
        res = _ai_model.generate_content(prompt)
        intent_res = extract_json(res.text)
        if intent_res and isinstance(intent_res, dict):
            return intent_res
        return default_intent
    except: return default_intent

# [V177] 리랭킹 연산 부하 축소: 후보군을 8개에서 4개로 줄여 AI 연산 속도 2배 향상
@st.cache_data(ttl=3600, show_spinner=False)
def rerank_results_ai(_ai_model, query, results, intent):
    if not results: return []
    safe_intent = intent if intent else {"target_mfr": "미지정", "target_item": "공통"}
    
    # 상위 4개 핵심 후보만 AI에게 전달하여 속도 최적화
    top_candidates = results[:4]
    candidates = []
    for r in top_candidates:
        candidates.append({
            "id": r.get('id'), 
            "mfr": r.get('manufacturer'),
            "item": r.get('measurement_item'),
            "model": r.get('model_name'), 
            "content": (r.get('content') or r.get('solution'))[:250]
        })
    
    target_mfr = safe_intent.get('target_mfr')
    target_item = safe_intent.get('target_item')
    
    prompt = f"""사용자 질문: "{query}"
    필수 조건 -> 제조사: {target_mfr}, 측정항목: {target_item}
    각 후보 지식의 정합성을 0-100점으로 평가해. 불일치 시 0점.
    후보 목록: {json.dumps(candidates, ensure_ascii=False)}
    응답형식(JSON): [{{"id": 1, "score": 95}}, ...]"""
    
    try:
        res = _ai_model.generate_content(prompt)
        scores = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in scores}
        for r in results: 
            r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True)
    except: return results

# [V177] 최종 요약문 캐싱: 동일 질문에 대해 즉시 답변 반환 (0초대 응답 핵심)
@st.cache_data(ttl=3600, show_spinner=False)
def generate_3line_summary(_ai_model, query, data_json):
    prompt = f"""질문: {query} 데이터: {data_json}
    현장 대원을 위한 조치 사항 3가지를 '반드시 3개의 번호가 붙은 리스트'로 요약해.
    [포맷 규칙]
    1. (핵심 조치 내용) - (기대 효과)
    2. (핵심 조치 내용) - (기대 효과)
    3. (핵심 조치 내용) - (기대 효과)
    - 문장 끝마다 반드시 줄바꿈(\\n\\n)을 두 번 넣을 것."""
    res = _ai_model.generate_content(prompt)
    return res.text

def generate_relevant_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n문장 단위로 줄바꿈하여 정밀 기술 리포트를 작성해줘."
    res = ai_model.generate_content(prompt)
    return res.text
