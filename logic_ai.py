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

@st.cache_data(ttl=3600, show_spinner=False)
def analyze_search_intent(_ai_model, query):
    # [V180] 어떠한 경우에도 None을 반환하지 않도록 기본 객체 선언
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
    except:
        return default_intent

@st.cache_data(ttl=3600, show_spinner=False)
def unified_rerank_and_summary_ai(_ai_model, query, results, intent):
    # [V180] intent 인자 무결성 확인
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    if not results: return [], "관련 지식을 찾지 못했습니다."
    
    target_mfr = safe_intent.get('target_mfr', '미지정')
    target_item = safe_intent.get('target_item', '공통')
    
    candidates = []
    for r in results[:5]:
        candidates.append({
            "id": r.get('id'), 
            "mfr": r.get('manufacturer'),
            "item": r.get('measurement_item'),
            "model": r.get('model_name'), 
            "content": (r.get('content') or r.get('solution'))[:300]
        })

    prompt = f"""[지시] 사용자 질문 "{query}"에 대해 후보들을 평가하고 핵심 조치를 요약해.
    필수 타겟 -> 제조사: {target_mfr}, 항목: {target_item}
    
    1. 각 후보의 신뢰도(0-100)를 평가해. (제조사 다르면 무조건 0점)
    2. 상위권 후보를 기반으로 '3줄 조치 가이드'를 작성해.
    
    [요약 포맷 규칙]
    1. (내용) - (효과)
    2. (내용) - (효과)
    3. (내용) - (효과)
    (문장 끝마다 \\n\\n 필수)
    
    후보: {json.dumps(candidates, ensure_ascii=False)}
    
    응답형식(JSON):
    {{
      "scores": [{{"id": 1, "score": 95}}, ...],
      "summary": "1. ...\\n\\n2. ...\\n\\n3. ..."
    }}"""
    
    try:
        res = _ai_model.generate_content(prompt)
        parsed = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in parsed.get('scores', [])}
        for r in results:
            r['rerank_score'] = score_map.get(r['id'], 0)
            
        final_results = sorted(results, key=lambda x: x['rerank_score'], reverse=True)
        return final_results, parsed.get('summary', "요약을 생성할 수 없습니다.")
    except:
        return results, "연산 중 오류가 발생했습니다."

def generate_relevant_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n문장 단위로 줄바꿈하여 정밀 기술 리포트를 작성해줘."
    res = ai_model.generate_content(prompt)
    return res.text
