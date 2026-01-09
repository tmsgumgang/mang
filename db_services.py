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

    def add_feedback(self, source_id, query, is_positive=True):
        try:
            if not is_positive:
                self.supabase.table("knowledge_blacklist").insert({"source_id": source_id, "query": query, "reason": "무관한 정보"}).execute()
            return True
        except: return False

    # [V138] 필터링이 강화된 통합 검색
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent):
        query = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 50})
        results = query.execute().data or []
        
        # AI가 분석한 의도(모델명/항목)가 있다면 필터링 강화
        target_model = intent.get('target_model')
        if target_model:
            # 모델명이 포함된 결과에 가산점을 주거나, 일치하지 않는 다른 모델 결과는 필터링
            filtered = [d for d in results if not d.get('model_name') or target_model.lower() in d.get('model_name','').lower()]
            return filtered if filtered else results
        return results

    def bulk_approve_file(self, table_name, file_name):
        try:
            self.supabase.table(table_name).update({"semantic_version": 1, "review_required": False}).eq("file_name", file_name).eq("semantic_version", 2).execute()
            return True
        except: return False
