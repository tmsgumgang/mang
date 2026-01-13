import re
import json
import google.generativeai as genai
import streamlit as st
# [New] 프롬프트 파일 불러오기
from prompts import PROMPTS 

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

# --------------------------------------------------------------------------------
# [V206] 자동 키워드 태깅(Auto-Tagging) 엔진
# --------------------------------------------------------------------------------
def extract_metadata_ai(ai_model, content):
    try:
        # [수정] 프롬프트 분리 적용
        prompt = PROMPTS["extract_metadata"].format(content=content[:2000])
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

@st.cache_data(ttl=3600, show_spinner=False)
def analyze_search_intent(_ai_model, query):
    default_intent = {
        "target_mfr": "미지정", 
        "target_model": "미지정", 
        "target_item": "공통",
        "target_action": "일반" # [New] 프롬프트에 맞춰 필드 추가
    }
    try:
        # [수정] 프롬프트 분리 적용
        prompt = PROMPTS["search_intent"].format(query=query)
        res = _ai_model.generate_content(prompt)
        intent_res = extract_json(res.text)
        if intent_res and isinstance(intent_res, dict):
            return intent_res
        return default_intent
    except:
        return default_intent

@st.cache_data(ttl=3600, show_spinner=False)
def quick_rerank_ai(_ai_model, query, results, intent):
    if not results: return []
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    
    candidates = []
    for r in results[:5]:
        candidates.append({
            "id": r.get('id'), 
            "mfr": r.get('manufacturer'), 
            "item": r.get('measurement_item'),
            "content": (r.get('content') or r.get('solution'))[:200]
        })

    # [수정] 프롬프트 분리 적용
    prompt = PROMPTS["rerank_score"].format(
        query=query, 
        mfr=safe_intent.get('target_mfr'), 
        item=safe_intent.get('target_item'), 
        candidates=json.dumps(candidates, ensure_ascii=False)
    )
    
    try:
        res = _ai_model.generate_content(prompt)
        scores = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in scores}
        for r in results: r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True)
    except: return results

# [V200 핵심] 팩트 고정(Fact-Lock) 스트리밍 요약 생성기
def generate_3line_summary_stream(ai_model, query, results):
    if not results:
        yield "검색 결과가 부족하여 요약을 생성할 수 없습니다."
        return

    # [Fact-Lock] 상위 1위 문서(가장 정확한 문서)를 'Primary Source'로 지정
    top_doc = results[0]
    top_content = f"★최우선참고자료(Fact Source): {top_doc.get('content') or top_doc.get('solution')}"
    
    other_context = []
    for r in results[1:3]:
        other_context.append(f"- 보조자료: {r.get('content') or r.get('solution')}")
    
    full_context = [top_content] + other_context
    
    # [수정] 프롬프트 분리 적용
    prompt = PROMPTS["summary_fact_lock"].format(
        query=query, 
        context=json.dumps(full_context, ensure_ascii=False)
    )
    
    response = ai_model.generate_content(prompt, stream=True)
    for chunk in response:
        if chunk.text:
            yield chunk.text

@st.cache_data(ttl=3600, show_spinner=False)
def unified_rerank_and_summary_ai(_ai_model, query, results, intent):
    if not results: return [], "관련 지식을 찾지 못했습니다."
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    candidates = [{"id":r['id'],"content":(r.get('content')or r.get('solution'))[:300]} for r in results[:5]]
    
    # [수정] 프롬프트 분리 적용
    prompt = PROMPTS["unified_rerank"].format(
        query=query, 
        safe_intent=safe_intent, 
        candidates=candidates
    )
    
    try:
        res = _ai_model.generate_content(prompt)
        parsed = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in parsed.get('scores', [])}
        for r in results: r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True), parsed.get('summary', "요약 불가")
    except: return results, "오류 발생"

# [V200 핵심] 팩트 고정(Fact-Lock) 심층 리포트
def generate_relevant_summary(ai_model, query, data):
    # [수정] 프롬프트 분리 적용
    prompt = PROMPTS["deep_report"].format(
        query=query, 
        data=data
    )
    res = ai_model.generate_content(prompt)
    return res.text

# [End of File]
