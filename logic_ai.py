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

# [V186] 리랭킹 전용 함수 (고속 처리를 위해 통합 엔진에서 다시 분리/최적화)
@st.cache_data(ttl=3600, show_spinner=False)
def quick_rerank_ai(_ai_model, query, results, intent):
    if not results: return []
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    
    # 상위 5개만 빠르게 평가
    candidates = []
    for r in results[:5]:
        candidates.append({
            "id": r.get('id'), 
            "mfr": r.get('manufacturer'), 
            "item": r.get('measurement_item'),
            "content": (r.get('content') or r.get('solution'))[:200]
        })

    prompt = f"""사용자 질문: "{query}"
    조건: 제조사 {safe_intent.get('target_mfr')}, 항목 {safe_intent.get('target_item')}
    각 후보의 적합성을 0-100점으로 평가해.
    후보: {json.dumps(candidates, ensure_ascii=False)}
    응답형식(JSON): [{{"id": 1, "score": 95}}, ...]"""
    
    try:
        res = _ai_model.generate_content(prompt)
        scores = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in scores}
        for r in results: r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True)
    except: return results

# [V186 핵심] 스트리밍 요약 생성기 (Generator)
# 텍스트가 완성될 때까지 기다리지 않고, 생성되는 족족 UI로 던져줍니다.
def generate_3line_summary_stream(ai_model, query, results):
    if not results:
        yield "검색 결과가 부족하여 요약을 생성할 수 없습니다."
        return

    # 요약에 참고할 데이터 (상위 3개)
    data_context = []
    for r in results[:3]:
        data_context.append(f"- {r.get('content') or r.get('solution')}")
    
    prompt = f"""질문: {query}
    참고 데이터: {json.dumps(data_context, ensure_ascii=False)}
    
    위 데이터를 바탕으로 현장 조치 가이드 3가지를 작성해.
    형식:
    1. (핵심 조치) - (효과)
    2. (핵심 조치) - (효과)
    3. (핵심 조치) - (효과)
    
    - 반드시 바로 출력을 시작할 것.
    - 문장 사이에는 줄바꿈을 두 번 넣어줘."""
    
    # stream=True 옵션으로 스트림 객체 생성
    response = ai_model.generate_content(prompt, stream=True)
    for chunk in response:
        if chunk.text:
            yield chunk.text

# 기존 통합 함수 유지 (하위 호환성 및 보존 지침 준수)
@st.cache_data(ttl=3600, show_spinner=False)
def unified_rerank_and_summary_ai(_ai_model, query, results, intent):
    # (V183 코드 내용 유지 - 생략 없이 보존됨)
    if not results: return [], "관련 지식을 찾지 못했습니다."
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    candidates = [{"id":r['id'],"content":(r.get('content')or r.get('solution'))[:300]} for r in results[:5]]
    prompt = f"질문:{query} 조건:{safe_intent} 후보:{candidates} 평가 및 3줄요약해. JSON응답."
    try:
        res = _ai_model.generate_content(prompt)
        parsed = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in parsed.get('scores', [])}
        for r in results: r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True), parsed.get('summary', "요약 불가")
    except: return results, "오류 발생"

def generate_relevant_summary(ai_model, query, data):
    prompt = f"질문: {query} 데이터: {data}\n문장 단위로 줄바꿈하여 정밀 기술 리포트를 작성해줘."
    res = ai_model.generate_content(prompt)
    return res.text
