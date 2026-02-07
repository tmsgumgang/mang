import re
import json
import google.generativeai as genai
import streamlit as st
from prompts import PROMPTS 

@st.cache_data(show_spinner=False)
def get_embedding(text):
    """
    [V243] 임베딩 모델 Fallback 로직 추가
    """
    cleaned_text = clean_text_for_db(text)
    try:
        # 1순위: 최신 모델
        result = genai.embed_content(model="models/text-embedding-004", content=cleaned_text, task_type="retrieval_document")
        return result['embedding']
    except Exception as e:
        # 2순위: 호환성 모델 (Fallback)
        try:
            result = genai.embed_content(model="models/embedding-001", content=cleaned_text, task_type="retrieval_document")
            return result['embedding']
        except Exception as e2:
            print(f"❌ Embedding Error: {e2}")
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
    [V303 수정] 리랭킹 시 Model Name을 포함하여 AI가 정확한 장비를 식별하도록 개선
    """
    if not results: return []
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    
    candidates = []
    # 상위 7개만 정밀 분석 (속도 최적화)
    for r in results[:7]:
        # [핵심 수정] 제조사/모델명/항목을 하나의 문자열로 합쳐서 AI에게 전달
        # 기존에는 model_name이 누락되어 있어서 '멍청한' 판단을 했음
        mfr = r.get('manufacturer', '')
        model = r.get('model_name', '')
        item = r.get('measurement_item', '')
        raw_content = (r.get('content') or r.get('solution') or "")[:300]
        
        # AI가 볼 문맥: "[시마즈 TOC-4200 (TOC)] 튜브 교체 방법은..."
        context_str = f"[{mfr} {model} ({item})] {raw_content}"
        
        candidates.append({
            "id": r.get('id'),
            "info": context_str  # 단순 content 대신 메타데이터가 포함된 info 전달
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
        
        if scores and isinstance(scores, list):
            score_map = {str(item['id']): item.get('score', 0) for item in scores}
            for r in results:
                # ID 타입 불일치 방지를 위해 str 변환 후 매칭
                r['rerank_score'] = score_map.get(str(r['id']), 0)
            return sorted(results, key=lambda x: x.get('rerank_score', 0), reverse=True)
        else:
            return results
    except: return results

def generate_3line_summary_stream(ai_model, query, results):
    """
    [V303 수정] 답변 생성 시 '출처(Metadata)'를 명시하여 팩트 그라운딩 강화
    """
    if not results:
        yield "검색 결과가 부족하여 요약을 생성할 수 없습니다."
        return

    # [핵심 수정] 내용(Content)만 주는 게 아니라 [누구의 문서인지] 꼬리표를 달아줌
    full_context = []
    
    # 1. 최우선 자료
    top_doc = results[0]
    top_meta = f"[{top_doc.get('manufacturer','')} {top_doc.get('model_name','')}]"
    top_content = f"★최우선참고자료(Fact Source): {top_meta} {top_doc.get('content') or top_doc.get('solution')}"
    full_context.append(top_content)
    
    # 2. 보조 자료
    for r in results[1:4]:
        sub_meta = f"[{r.get('manufacturer','')} {r.get('model_name','')}]"
        full_context.append(f"- 보조자료: {sub_meta} {r.get('content') or r.get('solution')}")
    
    # Context에 메타데이터가 포함되어야 AI가 '시마즈 TOC'라고 특정해서 말할 수 있음
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
# [NEW V252] Graph RAG 관계 추출 엔진
# --------------------------------------------------------------------------------
def extract_triples_from_text(ai_model, text):
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
