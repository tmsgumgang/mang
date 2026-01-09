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

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("file_name", file_name).or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').execute()
            return True, f"{len(res.data)}건 일괄 완료"
        except Exception as e: return False, str(e)

    # [V152] 하드 필터링 적용 검색 로직
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent):
        try:
            target_item = intent.get('target_item')
            target_model = intent.get('target_model')
            
            # 1. 기본 벡터 검색 실행
            results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            # 2. 메타데이터 일치 시 강력한 가중치 부여 및 비일치 항목 감점
            filtered_results = []
            for d in results:
                score_adj = 0
                # 항목(TOC, TN 등) 일치 시 대폭 가산
                if target_item and target_item.lower() in str(d.get('measurement_item', '')).lower():
                    score_adj += 0.5
                elif target_item: # 항목이 지정되었는데 일치하지 않으면 감점
                    score_adj -= 0.3
                
                # 모델명 일치 시 가산
                if target_model and target_model.lower() in str(d.get('model_name', '')).lower():
                    score_adj += 0.4
                
                d['similarity'] = (d.get('similarity') or 0) + score_adj
                filtered_results.append(d)
                
            return filtered_results
        except: return []

    def delete_record(self, table_name, row_id):
        try:
            res = self.supabase.table(table_name).delete().eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_vector(self, table_name, row_id, vec):
        try:
            self.supabase.table(table_name).update({"embedding": vec}).eq("id", row_id).execute()
            return True
        except: return False
