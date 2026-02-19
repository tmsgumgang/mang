import re
import json
import requests
import streamlit as st
import google.generativeai as genai
from prompts import PROMPTS 

# [V248] 임베딩 로직 안정화: REST API 직접 호출 (404 에러 원천 차단)
@st.cache_data(show_spinner=False)
def get_embedding(text):
    """
    - 구형 라이브러리의 내부 버그(404 에러)를 피하기 위해,
    - 라이브러리를 거치지 않고 구글 서버로 직접 데이터를 쏴서 벡터를 받아옵니다.
    """
    cleaned_text = clean_text_for_db(text)
    if not cleaned_text: 
        return []

    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        # 최신 모델부터 구형 모델까지 순서대로 구글 서버에 직접 찔러봅니다.
        models_to_try = ["text-embedding-004", "embedding-001"]
        last_error = ""

        for model_name in models_to_try:
            try:
                # 구글 서버 다이렉트 주소
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:embedContent?key={api_key}"
                headers = {'Content-Type': 'application/json'}
                payload = {
                    "model": f"models/{model_name}",
                    "content": {
                        "parts": [{"text": cleaned_text}]
                    }
                }
                
                # 라이브러리 없이 직접 통신!
                response = requests.post(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    res_data = response.json()
                    if 'embedding' in res_data and 'values' in res_data['embedding']:
                        return res_data['embedding']['values']
                else:
                    last_error = f"{response.status_code} - {response.text}"
                    print(f"⚠️ {model_name} 직접 호출 실패: {last_error}")
                    
            except Exception as req_err:
                last_error = str(req_err)
                print(f"⚠️ {model_name} 네트워크 에러: {last_error}")

        # 모든 모델 시도 실패 시
        error_msg = f"🚨 AI 임베딩 서버 직접 통신 실패.\n원인: {last_error}"
        print(error_msg)
        st.error(error_msg)
        return []

    except Exception as e:
        print(f"❌ 임베딩 함수 내부 에러: {e}")
        st.error(f"임베딩 로직 오류: {e}")
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
# [V206] 자동 키워드 태깅 (App.py의 어댑터와 호환)
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
    
    # [V245] 어댑터가 stream 요청도 처리하도록 설계됨
    response = ai_model.generate_content(prompt, stream=True)
    
    # 신형 라이브러리의 스트림 응답 처리
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
    graph_prompt = f"""
    You are an expert Data Engineer specializing in Knowledge Graphs.
    Analyze the provided technical text and extract relationships between entities.
    
    Target Entities: Device, Part, Symptom, Cause, Solution, Action, Value, Location, Manufacturer.
    Target Relations: 
    - causes (원인이다)
    - part_of (의 부품이다)
    - located_in (에 위치한다)
    - solved_by (로 해결된다)
    - has_status (상태를 가진다)
    - requires (을 필요로 한다)
    - manufactured_by (이 제조했다)

    IMPORTANT: 
    - Entities MUST be single nouns or short phrases.
    - Return ONLY a JSON array of objects.
    
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
