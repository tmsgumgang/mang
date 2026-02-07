import re
import json
import google.generativeai as genai
import streamlit as st
from prompts import PROMPTS 

@st.cache_data(show_spinner=False)
def get_embedding(text):
    """
    [V243] 임베딩 모델 Fallback 로직 추가 (004 모델 실패 시 001 사용)
    - Google API의 모델 버전 이슈나 지역 제한으로 인한 404 오류 방지
    """
    cleaned_text = clean_text_for_db(text)
    try:
        # 1순위: 최신 모델 시도 (성능 우수)
        result = genai.embed_content(model="models/text-embedding-004", content=cleaned_text, task_type="retrieval_document")
        return result['embedding']
    except Exception as e:
        # 2순위: 실패 시 안정화(구형) 모델 사용 (호환성 우수)
        try:
            # print(f"⚠️ 임베딩 모델 004 실패 -> 001로 전환: {e}")
            result = genai.embed_content(model="models/embedding-001", content=cleaned_text, task_type="retrieval_document")
            return result['embedding']
        except Exception as e2:
            print(f"❌ 모든 임베딩 모델 실패: {e2}")
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
        # JSON 포맷 보정 시도
        if cleaned.startswith('{') and not cleaned.endswith('}'): cleaned += '}'
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
    """
    [V303 지능 복구] 리랭킹 시 메타데이터(제조사/모델명)를 명시적으로 주입
    """
    if not results: return []
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    
    candidates = []
    for r in results[:7]: # 상위 7개만 정밀 분석
        # [핵심] 제조사와 모델명을 본문 앞에 붙여서 AI가 헷갈리지 않게 함
        meta_info = f"[{r.get('manufacturer', '')} {r.get('model_name', '')}]"
        raw_content = (r.get('content') or r.get('solution') or "")[:300]
        
        candidates.append({
            "id": r.get('id'), 
            "mfr": r.get('manufacturer'), 
            "item": r.get('measurement_item'),
            # AI에게 보여줄 때는 메타데이터와 본문을 합쳐서 전달
            "content": f"{meta_info} {raw_content}" 
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
        
        # 점수 매핑 (리스트 형태 체크)
        if scores and isinstance(scores, list):
            score_map = {str(item['id']): item.get('score', 0) for item in scores}
            for r in results:
                # 기존 ID가 int일 수도 있고 str일 수도 있으므로 str로 통일해서 비교
                r['rerank_score'] = score_map.get(str(r['id']), 0)
            return sorted(results, key=lambda x: x.get('rerank_score', 0), reverse=True)
        else:
            return results # 포맷 안맞으면 기존 순서 유지
    except: return results

def generate_3line_summary_stream(ai_model, query, results):
    """
    [V303 지능 복구] 답변 생성 시 '출처(Metadata)'를 포함하여 Fact Grounding 강화
    """
    if not results:
        yield "검색 결과가 부족하여 요약을 생성할 수 없습니다."
        return

    # [핵심 수정] 단순히 content만 나열하지 않고, [제조사 모델명]을 앞에 붙임
    full_context = []
    
    # 1. 최우선 자료 처리
    top_doc = results[0]
    top_meta = f"[{top_doc.get('manufacturer','')} {top_doc.get('model_name','')}]"
    top_content = f"★최우선참고자료(Fact Source): {top_meta} {top_doc.get('content') or top_doc.get('solution')}"
    full_context.append(top_content)
    
    # 2. 보조 자료 처리 (상위 3개까지)
    for r in results[1:4]:
        sub_meta = f"[{r.get('manufacturer','')} {r.get('model_name','')}]"
        full_context.append(f"- 보조자료: {sub_meta} {r.get('content') or r.get('solution')}")
    
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
    
    # 여기도 메타데이터 주입
    candidates = []
    for r in results[:5]:
        meta = f"[{r.get('manufacturer','')} {r.get('model_name','')}]"
        content = (r.get('content') or r.get('solution'))[:300]
        candidates.append({"id": r['id'], "content": f"{meta} {content}"})
    
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
# [NEW V252] Graph RAG 관계 추출 엔진 (소모품/설비/정의 관계 추가)
# --------------------------------------------------------------------------------
def extract_triples_from_text(ai_model, text):
    """
    텍스트에서 (주어) -> [관계] -> (목적어) 트리플을 추출합니다.
    [V252 업데이트] 소모품(consumable), 설비(is_facility_of), 정의(is_a) 등 상세 관계 추가
    """
    graph_prompt = f"""
    You are an expert Data Engineer specializing in Knowledge Graphs for Industrial/Environmental Facilities.
    Analyze the provided technical text and extract relationships between entities.
    
    Target Entities: Device, Part, Symptom, Cause, Solution, Action, Value, Location, Manufacturer, Consumable, Process, Station, Facility.
    
    Target Relations: 
    - causes (원인이다: A causes B)
    - part_of (부품이다: A is a mechanical component of Device B)
    - consumable_of (소모품이다: A is a disposable material for B. e.g., Reagent, Filter, Cable tie)
    - is_facility_of (설비이다: A is a major facility/equipment installed at Station B. e.g., MCC Panel -> Station)
    - is_a (종류이다: A is a type/category/instance of B. e.g., Iwon -> Measurement Station)
    - included_in (일부이다: A is a step, section, or logical part of B. e.g., 'Step 1' is included in 'Calibration Process')
    - located_in (위치한다: A is physically located in B)
    - solved_by (해결된다: Symptom A is solved by Action B)
    - has_status (상태다: Device A has status/symptom B)
    - requires (필요로 한다: Action A requires Tool/Item B)
    - manufactured_by (제조사다: Product A is made by Manufacturer B)

    IMPORTANT: 
    - Entities MUST be single nouns or short phrases (under 5 words). 
    - Do NOT include full sentences as entities.
    - Example 1: "The MCC Panel is installed at Iwon Station"
      -> {{"source": "MCC Panel", "relation": "is_facility_of", "target": "Iwon Station"}}
    - Example 2: "Iwon is a remote measurement station"
      -> {{"source": "Iwon", "relation": "is_a", "target": "Measurement Station"}}
    - Example 3: "Use cable ties for pump replacement" 
      -> {{"source": "Cable ties", "relation": "consumable_of", "target": "Pump replacement"}}

    Return ONLY a JSON array of objects. No markdown, no explanations.
    Format: [{{"source": "Entity A", "relation": "relation_type", "target": "Entity B"}}]

    Text to Analyze:
    {text[:3500]}
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
