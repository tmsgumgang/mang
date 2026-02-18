import re
import json
import google.generativeai as genai
import streamlit as st
from prompts import PROMPTS 

@st.cache_data(show_spinner=False)
def get_embedding(text):
    """
    [V244 안정화 패치]
    - 최신 모델(004)과 구형 라이브러리 간 호환성 문제 해결을 위해
    - 가장 안정적인 'embedding-001' 모델을 1순위로 사용합니다.
    - 001 모델은 task_type 파라미터를 지원하지 않으므로 제거했습니다.
    """
    cleaned_text = clean_text_for_db(text)
    
    # 1. 텍스트가 없으면 API 호출 방지 (비용/에러 절약)
    if not cleaned_text:
        return []

    try:
        # [변경 1순위] 안정적인 구형 모델 사용 (task_type 옵션 제거 필수)
        result = genai.embed_content(
            model="models/embedding-001", 
            content=cleaned_text
        )
        return result['embedding']
    except Exception as e:
        # 1차 실패 시 로그 출력
        print(f"⚠️ 1차 임베딩(001) 실패: {e}")
        
        try:
            # [변경 2순위] 1차가 안 될 경우에만 최신 모델 시도
            result = genai.embed_content(
                model="models/text-embedding-004", 
                content=cleaned_text,
                task_type="retrieval_document"
            )
            return result['embedding']
        except Exception as e2:
            # 최종 실패 시 에러 로그 출력
            print(f"❌ 모든 임베딩 모델 실패: {e2}")
            # 화면에도 에러 원인을 표시하여 디버깅 도움
            st.error(f"AI 임베딩 오류: {e2}")
            return []

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
        "target_action": "일반"
    }
    try:
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

def generate_3line_summary_stream(ai_model, query, results):
    if not results:
        yield "검색 결과가 부족하여 요약을 생성할 수 없습니다."
        return

    top_doc = results[0]
    top_content = f"★최우선참고자료(Fact Source): {top_doc.get('content') or top_doc.get('solution')}"
    
    other_context = []
    for r in results[1:3]:
        other_context.append(f"- 보조자료: {r.get('content') or r.get('solution')}")
    
    full_context = [top_content] + other_context
    
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

def generate_relevant_summary(ai_model, query, data):
    prompt = PROMPTS["deep_report"].format(
        query=query, 
        data=data
    )
    res = ai_model.generate_content(prompt)
    return res.text

# --------------------------------------------------------------------------------
# [NEW V246] Graph RAG 관계 추출 엔진 (제조사 관계 추가)
# --------------------------------------------------------------------------------
def extract_triples_from_text(ai_model, text):
    """
    텍스트에서 (주어) -> [관계] -> (목적어) 트리플을 추출합니다.
    """
    # Graph Extraction 전용 프롬프트 (제조사 관계 추가됨)
    graph_prompt = f"""
    You are an expert Data Engineer specializing in Knowledge Graphs.
    Analyze the provided technical text and extract relationships between entities.
    
    Target Entities: Device, Part, Symptom, Cause, Solution, Action, Value, Location, Manufacturer.
    Target Relations: 
    - causes (원인이다)
    - part_of (의 부품이다: Use for components inside a machine)
    - located_in (에 위치한다)
    - solved_by (로 해결된다)
    - has_status (상태를 가진다)
    - requires (을 필요로 한다)
    - manufactured_by (이 제조했다: Use when Entity B is the Brand/Maker of Entity A)

    IMPORTANT: 
    - Entities MUST be single nouns or short phrases (under 5 words). 
    - Do NOT include full sentences as entities.
    - If a sentence is "Use cable ties for pump replacement", extract: {{"source": "Pump replacement", "relation": "requires", "target": "Cable ties"}}
    - If "Shimadzu TOC analyzer has an error", extract: {{"source": "TOC analyzer", "relation": "manufactured_by", "target": "Shimadzu"}}

    Return ONLY a JSON array of objects. No markdown, no explanations.
    Format: [{{"source": "Entity A", "relation": "relation_type", "target": "Entity B"}}]

    Text to Analyze:
    {text[:2500]}
    """
    
    try:
        res = ai_model.generate_content(graph_prompt)
        triples = extract_json(res.text)
        if triples and isinstance(triples, list):
            return triples
        return []
    except Exception as e:
        print(f"Graph Extraction Error: {e}")
        return []
