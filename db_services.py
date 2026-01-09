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

    # [V144] 데이터 교정 및 라벨 저장 (리뷰 완료 처리)
    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            self.supabase.table(table_name).update({
                "manufacturer": mfr, "model_name": model, "measurement_item": item,
                "semantic_version": 1, "review_required": False
            }).eq("id", row_id).execute()
            return True
        except: return False

    # [V144] 장비 타겟팅 가중치 검색 (+0.3)
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent):
        try:
            results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            target_m = intent.get('target_model')
            if target_m:
                for d in results:
                    if target_m.lower() in str(d.get('model_name','')).lower():
                        d['similarity'] = (d.get('similarity') or 0) + 0.3
            return results
        except: return []

    # [V144] 파일 단위 일괄 승인
    def bulk_approve_file(self, table_name, file_name):
        try:
            self.supabase.table(table_name).update({"semantic_version": 1, "review_required": False}).eq("file_name", file_name).eq("semantic_version", 2).execute()
            return True
        except: return False
