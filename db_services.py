from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def keep_alive(self):
        try: self.supabase.table("knowledge_base").select("id").limit(1).execute()
        except: pass

    def get_penalty_counts(self):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").execute()
            return Counter([r['source_id'] for r in res.data])
        except: return {}

    # [V183] 세맨틱 피드백 저장: 질문 텍스트와 벡터를 함께 기록하여 맥락 학습 기반 마련
    def save_relevance_feedback(self, query, doc_id, t_name, score, query_vec=None):
        try:
            payload = {
                "query_text": query.strip(),
                "doc_id": doc_id,
                "table_name": t_name,
                "relevance_score": score
            }
            if query_vec:
                payload["query_embedding"] = query_vec
            
            self.supabase.table("relevance_feedback").insert(payload).execute()
            return True
        except: return False

    # [V183 핵심] 고속 맥락 필터링을 위한 배치 조회 함수
    # 질문 벡터를 이용해 과거에 '무관함' 판정을 받은 지식 ID들을 한꺼번에 가져옵니다.
    def get_semantic_context_blacklist(self, query_vec):
        try:
            # Supabase RPC 호출: 현재 질문과 95% 이상 유사한 과거 질문의 부정적 피드백 수집
            res = self.supabase.rpc("match_relevance_feedback_batch", {
                "input_embedding": query_vec,
                "match_threshold": 0.95
            }).execute()
            
            if res.data:
                # 무관함(-1) 평가를 받은 (테이블명, ID) 조합을 Set으로 반환하여 O(1) 검색 보장
                return {(item['table_name'], item['doc_id']) for item in res.data if item['relevance_score'] < 0}
            return set()
        except: return set()

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    # [V183 고속화] 배치 블랙리스트를 인자로 받아 메모리 상에서 즉시 필터링 수행
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text, context_blacklist=None):
        try:
            target_item = intent.get('target_item', '공통')
            target_model = intent.get('target_model', '미지정')
            results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            filtered_results = []
            keywords = [k for k in query_text.split() if len(k) > 1]
            t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"

            for d in results:
                # 1. [맥락 지능] 배치 블랙리스트에 포함된 지식은 0.0001초 만에 스킵
                if context_blacklist and (t_name, d['id']) in context_blacklist:
                    continue
                
                final_score = d.get('similarity') or 0
                
                # 2. 키워드 매칭 가산점 (Hybrid Component)
                content = (d.get('content') or d.get('solution') or "").lower()
                for kw in keywords:
                    if kw.lower() in content: final_score += 0.1
                
                # 3. 메타데이터 가중치 (Hard Meta Component)
                if target_item and target_item.lower() in str(d.get('measurement_item', '')).lower(): final_score += 0.5
                if target_model and target_model.lower() in str(d.get('model_name', '')).lower(): final_score += 0.4
                
                d['similarity'] = final_score
                filtered_results.append(d)
                
            return filtered_results
        except: return []

    def get_community_posts(self):
        try: return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content, mfr, model, item):
        try:
            payload = {"author": author, "title": title, "content": content, "manufacturer": mfr, "model_name": model, "measurement_item": item}
            res = self.supabase.table("community_posts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_community_post(self, post_id, title, content, mfr, model, item):
        try:
            payload = {"title": title, "content": content, "manufacturer": mfr, "model_name": model, "measurement_item": item}
            res = self.supabase.table("community_posts").update(payload).eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    def delete_community_post(self, post_id):
        try:
            res = self.supabase.table("community_posts").delete().eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    def get_comments(self, post_id):
        try: return self.supabase.table("community_comments").select("*").eq("post_id", post_id).order("created_at").execute().data
        except: return []

    def add_comment(self, post_id, author, content):
        try:
            res = self.supabase.table("community_comments").insert({"post_id": post_id, "author": author, "content": content}).execute()
            return True if res.data else False
        except: return False

    def promote_to_knowledge(self, issue, solution, mfr, model, item):
        try:
            from logic_ai import get_embedding
            payload = {"domain": "기술지식", "issue": issue, "solution": solution, "embedding": get_embedding(issue), "semantic_version": 1, "is_verified": True, "manufacturer": str(mfr).strip() or "미지정", "model_name": str(model).strip() or "미지정", "measurement_item": str(item).strip() or "공통"}
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("file_name", file_name).or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').execute()
            return True, f"{len(res.data)}건 일괄 분류 완료"
        except Exception as e: return False, str(e)

    def update_vector(self, table_name, row_id, vec):
        try: self.supabase.table(table_name).update({"embedding": vec}).eq("id", row_id).execute(); return True
        except: return False

    def delete_record(self, table_name, row_id):
        try:
            res = self.supabase.table(table_name).delete().eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
