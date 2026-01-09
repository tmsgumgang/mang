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

    # [V141] 라벨 정보 현장 교정 및 저장
    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            self.supabase.table(table_name).update({
                "manufacturer": mfr, "model_name": model, "measurement_item": item,
                "semantic_version": 1, "review_required": False
            }).eq("id", row_id).execute()
            return True
        except: return False

    # [V141] 모델명 일치 시 가중치 부여
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent):
        results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 50}).execute().data or []
        target_m = intent.get('target_model')
        if target_m:
            for d in results:
                if target_m.lower() in str(d.get('model_name','')).lower():
                    d['similarity'] = (d.get('similarity') or 0) + 0.3
        return results

    def bulk_approve_file(self, table_name, file_name):
        try:
            self.supabase.table(table_name).update({"semantic_version": 1, "review_required": False}).eq("file_name", file_name).eq("semantic_version", 2).execute()
            return True
        except: return False
