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

    def get_blacklist_ids(self, query):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
            return [r['source_id'] for r in res.data]
        except: return []

    def match_manual_db(self, query_vec, threshold):
        return self.supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []

    def match_knowledge_db(self, query_vec, threshold):
        return self.supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
