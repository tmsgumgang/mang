import re
import json
import google.generativeai as genai
import streamlit as st
from prompts import PROMPTS 

@st.cache_data(show_spinner=False)
def get_embedding(text):
    """[V243] 임베딩 모델 Fallback 로직 추가"""
    cleaned_text = clean_text_for_db(text)
    try:
        result = genai.embed_content(model="models/text-embedding-004", content=cleaned_text, task_type="retrieval_document")
        return result['embedding']
    except Exception:
        try:
            result = genai.embed_content(model="models/embedding-001", content=cleaned_text, task_type="retrieval_document")
            return result['embedding']
        except Exception: return []

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
    default_intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통", "target_action": "일반"}
    try:
        prompt = PROMPTS["search_intent"].format(query=query)
        res = _ai_model.generate_content(prompt)
        intent_res = extract_json(res.text)
        if intent_res and isinstance(intent_res, dict): return intent_res
        return default_intent
    except: return default_intent

@st.cache_data(ttl=3600, show_spinner=False)
def quick_rerank_ai(_ai_model, query, results, intent):
    """
    [V311] 리랭킹 시 그래프 데이터 가중치 부여 및 메타데이터 주입
    """
    if not results: return []
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    
    candidates = []
    # 상위 8개 정밀 분석
    for r in results[:8]:
        mfr = r.get('manufacturer', '')
        model = r.get('model_name', '')
        item = r.get('measurement_item', '')
        raw_content = (r.get('content') or r.get('solution') or "")[:400]
        
        # [핵심] 그래프 데이터 식별 및 강조
        is_graph = (r.get('source_table') == 'knowledge_graph') or ('지식그래프' in str(mfr))
        if is_graph:
            context_str = f"🔥[핵심인과관계/지식그래프] {raw_content}"
        else:
            context_str = f"[{mfr} {model} ({item})] {raw_content}"
        
        candidates.append({"id": r.get('id'), "info": context_str})

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
            for r in results: r['rerank_score'] = score_map.get(str(r['id']), 0)
            return sorted(results, key=lambda x: x.get('rerank_score', 0), reverse=True)
        return results
    except: return results

def generate_3line_summary_stream(ai_model, query, results):
    """
    [V311] 답변 생성 시 그래프 데이터(Key Insight)와 일반 문서를 구분하여 제공
    """
    if not results:
        yield "검색 결과가 부족하여 요약을 생성할 수 없습니다."
        return

    full_context = []
    
    # 1. 데이터를 그래프(족보)와 일반 문서로 분류
    graph_data = []
    manual_data = []
    
    for r in results:
        is_graph = (r.get('source_table') == 'knowledge_graph') or ('지식그래프' in str(r.get('manufacturer', '')))
        mfr = r.get('manufacturer', '미지정')
        model = r.get('model_name', '공통')
        content = (r.get('content') or r.get('solution') or "").strip()
        
        if is_graph:
            # [Smart Point] 그래프 데이터는 "결정적 단서"로 포장
            graph_data.append(f"💡 결정적 단서 (Key Insight/Graph): {content}")
        else:
            # 일반 문서는 출처 명시
            manual_data.append(f"- 문서자료: [{mfr} {model}] {content}")
            
    # 2. 문맥 조합: 그래프 데이터를 최상단에 배치하여 AI가 먼저 읽게 함 (앵커링 효과)
    # 그래프 데이터는 최대 3개, 매뉴얼은 최대 4개로 제한하여 Context Window 효율화
    final_context_list = graph_data[:3] + manual_data[:4]
    
    prompt = PROMPTS["summary_fact_lock"].format(
        query=query, 
        context=json.dumps(final_context_list, ensure_ascii=False)
    )
    
    response = ai_model.generate_content(prompt, stream=True)
    for chunk in response:
        if chunk.text: yield chunk.text

@st.cache_data(ttl=3600, show_spinner=False)
def unified_rerank_and_summary_ai(_ai_model, query, results, intent):
    if not results: return [], "관련 지식을 찾지 못했습니다."
    safe_intent = intent if (intent and isinstance(intent, dict)) else {"target_mfr": "미지정", "target_item": "공통"}
    
    candidates = []
    for r in results[:6]:
        is_graph = (r.get('source_table') == 'knowledge_graph')
        meta = "🔥[지식그래프]" if is_graph else f"[{r.get('manufacturer','')} {r.get('model_name','')}]"
        content = (r.get('content') or r.get('solution'))[:300]
        candidates.append({"id": r['id'], "content": f"{meta} {content}"})
    
    prompt = PROMPTS["unified_rerank"].format(query=query, safe_intent=safe_intent, candidates=candidates)
    
    try:
        res = _ai_model.generate_content(prompt)
        parsed = extract_json(res.text)
        score_map = {item['id']: item['score'] for item in parsed.get('scores', [])}
        for r in results: r['rerank_score'] = score_map.get(r['id'], 0)
        return sorted(results, key=lambda x: x['rerank_score'], reverse=True), parsed.get('summary', "요약 불가")
    except: return results, "오류 발생"

def generate_relevant_summary(ai_model, query, data):
    prompt = PROMPTS["deep_report"].format(query=query, data=data)
    res = ai_model.generate_content(prompt)
    return res.text

# [V252] Graph RAG 관계 추출 엔진
def extract_triples_from_text(ai_model, text):
    graph_prompt = f"""
    You are an expert Data Engineer specializing in Knowledge Graphs.
    Target Relations: causes, part_of, consumable_of, is_facility_of, is_a, included_in, located_in, solved_by, has_status, requires, manufactured_by.
    Return ONLY a JSON array. Format: [{{"source": "A", "relation": "causes", "target": "B"}}]
    Text: {text[:3500]}
    """
    try:
        res = ai_model.generate_content(graph_prompt)
        triples = extract_json(res.text)
        return triples if isinstance(triples, list) else []
    except: return []
