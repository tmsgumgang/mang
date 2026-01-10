from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def keep_alive(self):
        try: self.supabase.table("knowledge_base").select("id").limit(1).execute()
        except: pass

    # [V170 핵심] 특정 질문과 특정 지식 사이의 연관성 평가 저장
    def save_relevance_feedback(self, query, doc_id, t_name, score):
        try:
            payload = {
                "query_text": query.strip(),
                "doc_id": doc_id,
                "table_name": t_name,
                "relevance_score": score
            }
            self.supabase.table("relevance_feedback").insert(payload).execute()
            return True
        except: return False

    # [V170 핵심] 현재 질문에 대해 과거에 누적된 연관성 가중치 합산 추출
    def get_query_relevance_boost(self, query, doc_id, t_name):
        try:
            res = self.supabase.table("relevance_feedback")\
                .select("relevance_score")\
                .eq("query_text", query.strip())\
                .eq("doc_id", doc_id)\
                .eq("table_name", t_name)\
                .execute()
            return sum([item['relevance_score'] for item in res.data]) if res.data else 0
        except: return 0

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    # [V170] 하이브리드 검색 + 맥락적 연관성 가중치 결합 로직
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text):
        try:
            target_item = intent.get('target_item')
            target_model = intent.get('target_model')
            results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            filtered_results = []
            keywords = [k for k in query_text.split() if len(k) > 1]
            t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"

            for d in results:
                # 1. 기본 벡터 유사도
                final_score = d.get('similarity') or 0
                
                # 2. 키워드 매칭 가산점 (Hybrid)
                content = (d.get('content') or d.get('solution') or "").lower()
                for kw in keywords:
                    if kw.lower() in content: final_score += 0.1
                
                # 3. [V170] 맥락적 연관성 가중치 (Feedback)
                # 이 질문에 대해 이 문서가 과거에 얻은 연관성 점수를 합산 반영
                rel_boost = self.get_query_relevance_boost(query_text, d['id'], t_name)
                final_score += (rel_boost * 0.1) # 추천 1건당 10% 가산 또는 감점
                
                # 4. 메타데이터 필터링 가중치
                if target_item and target_item.lower() in str(d.get('measurement_item', '')).lower(): final_score += 0.5
                elif target_item: final_score -= 0.3
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
