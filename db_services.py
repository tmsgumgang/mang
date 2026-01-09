from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def keep_alive(self):
        try: self.supabase.table("knowledge_base").select("id").limit(1).execute()
        except: pass

    # [V137] 페널티 데이터 로드
    def get_penalty_counts(self):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").execute()
            return Counter([r['source_id'] for r in res.data])
        except: return {}

    # [V137] 피드백 저장 로직 복구
    def add_feedback(self, source_id, query, is_positive=True):
        try:
            if not is_positive:
                # 부정 피드백 시 블랙리스트(페널티) 테이블에 추가
                self.supabase.table("knowledge_blacklist").insert({
                    "source_id": source_id,
                    "query": query,
                    "reason": "사용자 부정 피드백"
                }).execute()
            return True
        except: return False

    def match_manual_db(self, query_vec, threshold):
        return self.supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []

    def match_knowledge_db(self, query_vec, threshold):
        return self.supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []

    def bulk_approve_file(self, table_name, file_name):
        try:
            self.supabase.table(table_name).update({"semantic_version": 1, "review_required": False}).eq("file_name", file_name).eq("semantic_version", 2).execute()
            return True
        except: return False
