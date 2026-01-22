from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    # =========================================================
    # [Helper] 데이터 정규화
    # =========================================================
    def _normalize_tags(self, raw_tags):
        if not raw_tags or str(raw_tags).lower() in ['none', 'nan', 'null']:
            return "공통"
        tags = [t.strip() for t in str(raw_tags).split(',')]
        seen = set()
        clean_tags = []
        for tag in tags:
            if tag and tag not in seen:
                clean_tags.append(tag)
                seen.add(tag)
        return ", ".join(clean_tags) if clean_tags else "공통"

    def _clean_text(self, text):
        if not text or str(text).lower() in ['none', 'nan', 'null', '미지정']:
            return "미지정"
        return str(text).strip()

    def keep_alive(self):
        try: self.supabase.table("knowledge_base").select("id").limit(1).execute()
        except: pass

    def get_penalty_counts(self):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").execute()
            return Counter([r['source_id'] for r in res.data])
        except: return {}

    def save_relevance_feedback(self, query, doc_id, t_name, score, query_vec=None, reason=None):
        try:
            payload = {
                "query_text": query.strip(),
                "doc_id": doc_id,
                "table_name": t_name,
                "relevance_score": score,
                "reason": reason
            }
            if query_vec:
                payload["query_embedding"] = query_vec
            self.supabase.table("relevance_feedback").insert(payload).execute()
            return True
        except: return False

    def get_semantic_context_blacklist(self, query_vec):
        try:
            res = self.supabase.rpc("match_relevance_feedback_batch", {
                "input_embedding": query_vec,
                "match_threshold": 0.95
            }).execute()
            if res.data:
                return {(item['table_name'], item['doc_id']) for item in res.data if item['relevance_score'] < 0}
            return set()
        except: return set()

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            clean_mfr = self._clean_text(mfr)
            clean_model = self._clean_text(model)
            clean_item = self._normalize_tags(item)
            payload = {
                "manufacturer": clean_mfr, 
                "model_name": clean_model, 
                "measurement_item": clean_item, 
                "semantic_version": 1, 
                "review_required": False
            }
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text, context_blacklist=None):
        try:
            target_item = intent.get('target_item', '공통')
            vector_results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            keyword_results = []
            search_candidates = set()
            if target_item and target_item not in ['공통', '미지정', 'none', 'unknown']:
                search_candidates.add(target_item.strip())
                search_candidates.add(target_item.replace(" ", ""))
            
            if not search_candidates:
                words = query_text.split()
                for w in words:
                    if len(w) >= 2 and w not in ['알려줘', '어떻게', '교체', '방법', '준비물']:
                        search_candidates.add(w)
            
            if search_candidates:
                t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"
                query_builder = self.supabase.table(t_name).select("*")
                or_conditions = []
                for kw in search_candidates:
                    if not kw: continue
                    if t_name == "manual_base":
                        or_conditions.append(f"measurement_item.ilike.%{kw}%")
                        or_conditions.append(f"model_name.ilike.%{kw}%")
                        or_conditions.append(f"content.ilike.%{kw}%")
                    else:
                        or_conditions.append(f"measurement_item.ilike.%{kw}%")
                        or_conditions.append(f"issue.ilike.%{kw}%")
                        or_conditions.append(f"solution.ilike.%{kw}%")
                
                if or_conditions:
                    final_filter = ",".join(or_conditions)
                    res = query_builder.or_(final_filter).limit(10).execute()
                    if res.data:
                        for d in res.data:
                            d['similarity'] = 0.99
                            keyword_results.append(d)

            merged_map = {}
            for d in vector_results: merged_map[d['id']] = d
            for d in keyword_results: merged_map[d['id']] = d 
                
            final_results_list = list(merged_map.values())
            filtered_results = []
            keywords = [k for k in query_text.split() if len(k) > 1]
            t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"

            for d in final_results_list:
                if context_blacklist and (t_name, d['id']) in context_blacklist:
                    continue
                final_score = d.get('similarity') or 0
                content = (d.get('content') or d.get('solution') or "").lower()
                for kw in keywords:
                    if kw.lower() in content: final_score += 0.1
                d['similarity'] = final_score
                filtered_results.append(d)
            return filtered_results
        except Exception as e: return []

    def search_keyword_fallback(self, query_text):
        keywords = [k for k in query_text.split() if len(k) >= 2]
        if not keywords: return []
        target_keyword = max(keywords, key=len)
        try:
            response = self.supabase.table("manual_base").select("*").or_(f"content.ilike.%{target_keyword}%,model_name.ilike.%{target_keyword}%").limit(5).execute()
            docs = response.data
            for d in docs:
                d['similarity'] = 0.98; d['source_table'] = 'manual_base'; d['is_verified'] = False 
            return docs
        except: return []

    def get_community_posts(self):
        try: return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content, mfr, model, item):
        try:
            payload = {"author": author, "title": title, "content": content, "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item)}
            res = self.supabase.table("community_posts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_community_post(self, post_id, title, content, mfr, model, item):
        try:
            payload = {"title": title, "content": content, "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item)}
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

    def promote_to_knowledge(self, issue, solution, mfr, model, item, author="익명"):
        try:
            from logic_ai import get_embedding
            payload = {
                "domain": "기술지식", "issue": issue, "solution": solution, "embedding": get_embedding(issue), 
                "semantic_version": 1, "is_verified": True, 
                "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item),
                "registered_by": author 
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            clean_mfr = self._clean_text(mfr)
            clean_model = self._clean_text(model)
            clean_item = self._normalize_tags(item)
            payload = {
                "manufacturer": clean_mfr, 
                "model_name": clean_model, 
                "measurement_item": clean_item, 
                "semantic_version": 1, 
                "review_required": False
            }
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

    # =========================================================
    # [V233] 📦 소모품 재고관리 (Inventory)
    # =========================================================
    def get_inventory_items(self):
        try:
            return self.supabase.table("inventory_items").select("*").order("category").order("item_name").execute().data
        except: return []

    def check_item_exists(self, name, model):
        try:
            res = self.supabase.table("inventory_items").select("*").eq("item_name", name).eq("model_name", model).execute()
            if res.data and len(res.data) > 0:
                return res.data[0] 
            return None
        except: return None

    def update_inventory_general(self, item_id, updates, worker):
        try:
            current = self.supabase.table("inventory_items").select("*").eq("id", item_id).execute()
            if not current.data: return False, "항목을 찾을 수 없음"
            
            old_data = current.data[0]
            old_qty = old_data.get('current_qty', 0)
            
            self.supabase.table("inventory_items").update(updates).eq("id", item_id).execute()
            
            if 'current_qty' in updates:
                new_qty = updates['current_qty']
                if old_qty != new_qty:
                    diff = new_qty - old_qty
                    log_type = "입고" if diff > 0 else "출고"
                    reason = f"대시보드 직접 수정 ({old_qty} → {new_qty})"
                    self.log_inventory_change(item_id, log_type, abs(diff), worker, reason)
            
            return True, "수정 성공"
        except Exception as e:
            return False, str(e)

    def update_inventory_qty(self, item_id, new_qty, worker):
        try:
            current = self.supabase.table("inventory_items").select("current_qty").eq("id", item_id).execute()
            old_qty = current.data[0]['current_qty'] if current.data else 0
            
            if old_qty == new_qty: return True, "변경 없음"

            self.supabase.table("inventory_items").update({"current_qty": new_qty}).eq("id", item_id).execute()
            
            diff = new_qty - old_qty
            log_type = "입고" if diff > 0 else "출고"
            reason = f"엑셀 갱신 ({old_qty} → {new_qty})"
            
            self.log_inventory_change(item_id, log_type, abs(diff), worker, reason)
            return True, "갱신 성공"
        except Exception as e:
            return False, str(e)

    def add_inventory_item(self, cat, name, model, loc, mfr, measure_val, desc, initial_qty, worker):
        try:
            clean_mfr = self._clean_text(mfr)
            clean_desc = self._clean_text(desc)
            clean_measure = self._normalize_tags(measure_val)
            
            payload = {
                "category": cat,
                "item_name": name,
                "model_name": model,
                "location": loc,
                "manufacturer": clean_mfr, 
                "measurement_item": clean_measure,
                "description": clean_desc,
                "current_qty": 0 
            }
            res = self.supabase.table("inventory_items").insert(payload).execute()
            
            if res.data:
                new_item_id = res.data[0]['id']
                if initial_qty > 0:
                    self.log_inventory_change(new_item_id, "입고", initial_qty, worker, "신규 품목 등록 (초기 재고)")
                return True, "성공"
            return False, "데이터베이스가 응답하지 않습니다."
        except Exception as e: 
            return False, str(e)

    def log_inventory_change(self, item_id, c_type, qty, worker, reason):
        try:
            payload = {
                "item_id": item_id,
                "change_type": c_type,
                "quantity": qty,
                "worker_name": worker,
                "reason": reason
            }
            res = self.supabase.table("inventory_logs").insert(payload).execute()
            return True if res.data else False
        except Exception as e:
            print(f"Inventory Log Error: {e}")
            return False

    def delete_inventory_item(self, item_id):
        try:
            self.supabase.table("inventory_items").delete().eq("id", item_id).execute()
            return True
        except: return False
    
    def get_inventory_logs(self, item_id=None):
        try:
            query = self.supabase.table("inventory_logs").select("*, inventory_items(item_name)").order("created_at", desc=True).limit(50)
            if item_id:
                query = query.eq("item_id", item_id)
            return query.execute().data
        except: return []

    # =========================================================
    # [V234 Final] 🤖 챗봇용 재고 검색 함수
    # =========================================================
    def search_inventory_for_chat(self, query_text):
        try:
            stop_words = ['재고', '수량', '몇개', '몇', '개', '있어', '있나요', '알려줘', '확인', '조회', '어디', '있니', '현황', '보여줘', '소모품']
            keywords = [k for k in query_text.split() if k not in stop_words and len(k) >= 2]

            if not keywords: return None

            query = self.supabase.table("inventory_items").select("*")
            or_filters = []
            for kw in keywords:
                or_filters.append(f"category.ilike.%{kw}%")
                or_filters.append(f"item_name.ilike.%{kw}%")
                or_filters.append(f"model_name.ilike.%{kw}%")
                or_filters.append(f"description.ilike.%{kw}%")
                or_filters.append(f"manufacturer.ilike.%{kw}%")
                or_filters.append(f"measurement_item.ilike.%{kw}%")
            
            if not or_filters: return None
            
            final_filter = ",".join(or_filters)
            res = query.or_(final_filter).execute()
            
            if not res.data: 
                return f"🔍 **'{', '.join(keywords)}'**에 대한 재고 정보가 없습니다.\n(혹시 오타가 있는지 확인해주세요. 예: valve vs vavle)"
            
            results = res.data
            msg = f"📦 **재고 검색 결과 ({len(results)}건):**\n"
            
            for item in results[:10]: 
                cat = item.get('category', '-')
                name = item.get('item_name', '이름없음')
                qty = item.get('current_qty', 0)
                loc = item.get('location', '위치미정')
                
                extra_info = []
                if item.get('model_name'): extra_info.append(item['model_name'])
                if item.get('description'): extra_info.append(item['description'])
                info_str = f"({' / '.join(extra_info)})" if extra_info else ""
                
                msg += f"- [{cat}] **{name}**: {qty}개 (위치: {loc}) {info_str}\n"
            
            if len(results) > 10:
                msg += f"\n(그 외 {len(results)-10}건 더 있음)"
                
            return msg
            
        except Exception as e:
            return f"재고 검색 중 오류 발생: {str(e)}"

    # =========================================================
    # [V236] 🕸️ 지식 그래프(Knowledge Graph) 저장 및 조회
    # =========================================================
    def save_knowledge_triples(self, doc_id, triples):
        """
        AI가 추출한 트리플(관계 데이터)을 DB에 저장합니다.
        """
        if not triples: return False
        
        try:
            # 대량 삽입 (Bulk Insert) 준비
            data_to_insert = []
            for t in triples:
                if t.get('source') and t.get('target'):
                    data_to_insert.append({
                        "source": self._clean_text(t['source']),
                        "relation": t.get('relation', 'related_to'),
                        "target": self._clean_text(t['target']),
                        "doc_id": doc_id
                    })
            
            if data_to_insert:
                self.supabase.table("knowledge_graph").insert(data_to_insert).execute()
                return True
            return False
        except Exception as e:
            print(f"Graph Save Error: {e}")
            return False

    def search_graph_relations(self, keyword):
        """
        특정 키워드와 연결된 지식 그래프(인과관계)를 검색합니다.
        """
        try:
            # source나 target에 키워드가 포함된 모든 관계 조회
            res = self.supabase.table("knowledge_graph").select("*")\
                .or_(f"source.ilike.%{keyword}%,target.ilike.%{keyword}%")\
                .limit(20).execute()
            return res.data
        except: return []
