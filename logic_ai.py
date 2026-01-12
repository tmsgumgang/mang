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

# --------------------------------------------------------------------------------
# [V206] 자동 키워드 태깅(Auto-Tagging) 엔진
# 목표: 문서 내의 모든 중요 부품/장비를 콤마로 나열하여 검색 적중률 극대화
# --------------------------------------------------------------------------------
def extract_metadata_ai(ai_model, content):
    try:
        prompt = f"""
        [Role] You are a Database Engineer responsible for labeling technical documents.
        [Task] Analyze the provided text and extract metadata for search optimization.
        
        [Text]
        {content[:2000]}
        
        [Rules]
        1. **manufacturer**: Identify the maker. If unknown/general, use "공통".
        2. **model_name**: Identify the specific model. If multiple parts are described, give a collective name (e.g., 'Water Sampling Panel', 'Pump System').
        3. **measurement_item**: This is CRITICAL. List **ALL** equipment, parts, components, and technical keywords mentioned in the text.
           - Use COMMAS to separate them.
           - Example: "Breaker, PLC, Relay, Inverter, EOCR"
           - Do NOT pick just one. List everything a user might search for.
        
        [Output Format (JSON)]
        {{"manufacturer": "...", "model_name": "...", "measurement_item": "..."}}
        """
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
    
    prompt = f"""[Role] You are a strict technical manual assistant.
    [Question] {query}
    [Data] {json.dumps(full_context, ensure_ascii=False)}
    
    [Mandatory Rules]
    1. **NO Hallucination:** Use ONLY the provided [Data]. Do NOT add general knowledge or safety rules (e.g., helmet, gloves) unless explicitly stated in [Data].
    2. **Specific Nouns:** When asked for 'tools' or 'parts', list the EXACT specific names found in the data (e.g., 'Monkey Spanner', 'Cable Tie', 'PL-50-...').
    3. **Silence on Unknowns:** If the data does not contain the answer, say "문서에 관련 정보가 명시되어 있지 않습니다." Do not make things up.
    4. **Language:** Korean.
    
    [Output Format]
    1. (핵심 내용) - (설명)
    2. (핵심 내용) - (설명)
    3. (핵심 내용) - (설명)
    
    Start output immediately."""
    
    response = ai_model.generate_content(prompt, stream=True)
    for chunk in response:
        if chunk.text:
            yield chunk.text

@st.cache_data(ttl=3600, show_spinner=False)
def unified_rerank_and_summary_ai(_ai_model, query, results, intent):
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

# [V200 핵심] 팩트 고정(Fact-Lock) 심층 리포트
def generate_relevant_summary(ai_model, query, data):
    prompt = f"""
    [역할] 너는 팩트 기반의 기술 리포트 작성가야. 절대 상상하지 마.
    [질문] {query}
    [데이터] {data}
    
    [지시사항 - 절대 준수]
    1. **오직 [데이터]에 있는 내용만으로** 리포트를 작성해.
    2. 데이터에 없는 '일반적인 상식', '통상적인 절차', '안전 수칙'은 절대 덧붙이지 마.
    3. 사용자가 준비물을 물으면 데이터에 있는 **구체적인 품명**만 나열해.
    4. 문장 단위로 줄바꿈하여 가독성 있게 작성해.
    """
    res = ai_model.generate_content(prompt)
    return res.text

# [End of File]
