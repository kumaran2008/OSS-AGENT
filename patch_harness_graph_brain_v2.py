from pathlib import Path

target = Path("agent/pa_scaffolder/engine_harness.py")
code = target.read_text(encoding="utf-8")

# 1. Update Context Retrieval Block
old_context_block = """        # -------------------------------------------------------------
        # 3. Pull Recent Context from Memory
        # -------------------------------------------------------------
        recent_context = []
        try:
            with self.memory_graph._get_conn() as conn:
                rows = conn.execute(
                    "SELECT properties FROM nodes WHERE node_type = 'episodic' ORDER BY updated_at DESC LIMIT 2"
                ).fetchall()
                for (prop_str,) in rows:
                    if prop_str:
                        p = json.loads(prop_str)
                        recent_context.append(f"User: {p.get('utterance', '')} -> {self.config.agent_name}: {p.get('response', '')}")
        except Exception:
            pass"""

new_context_block = """        # -------------------------------------------------------------
        # 3. Pull Associative Context via GraphBrain v2 (Hybrid RRF Search)
        # -------------------------------------------------------------
        recent_context = []
        try:
            # Query memory using hybrid FTS5 BM25 + Vector Dot Product
            relevant_nodes = self.memory_graph.get_relevant_context(clean_text if clean_text else raw_text, top_k=2)
            for node in relevant_nodes:
                p = node.get("properties", {})
                if "utterance" in p and "response" in p:
                    recent_context.append(f"User: {p['utterance']} -> {self.config.agent_name}: {p['response']}")
                else:
                    recent_context.append(f"Fact [{node.get('label')}]: {json.dumps(p)}")
        except Exception:
            pass"""

if old_context_block in code:
    code = code.replace(old_context_block, new_context_block)
    print("[✓] Replaced legacy LIMIT 2 query with GraphBrain v2 Hybrid Retrieval.")
else:
    print("[i] Context query block already updated or using dynamic format.")

# 2. Update Node Persistence Block
old_save_block = """        # -------------------------------------------------------------
        # 5. PERSIST TURN INTO MEMORY GRAPH
        # -------------------------------------------------------------
        try:
            self.memory_graph.add_or_update_node(
                node_id=f"Turn_{int(time.time() * 1000)}",
                node_type=NodeType.EPISODIC,
                metadata={
                    "utterance": raw_text,
                    "intent": intent,
                    "response": spoken_text,
                    "backend": backend_label
                }
            )
        except Exception:
            pass"""

new_save_block = """        # -------------------------------------------------------------
        # 5. PERSIST TURN INTO GRAPHBRAIN v2 (FTS5 + VECTOR EMBEDDED)
        # -------------------------------------------------------------
        try:
            turn_id = f"Turn_{int(time.time() * 1000)}"
            self.memory_graph.add_or_update_node(
                node_id=turn_id,
                node_type=NodeType.EPISODIC,
                label=f"Turn_{intent}",
                metadata={
                    "utterance": raw_text,
                    "clean_utterance": clean_text,
                    "intent": intent,
                    "response": spoken_text,
                    "backend": backend_label
                }
            )
        except Exception:
            pass"""

if old_save_block in code:
    code = code.replace(old_save_block, new_save_block)
    print("[✓] Updated turn storage to GraphBrain v2 schema.")

target.write_text(code, encoding="utf-8")
print("[✓] engine_harness.py successfully integrated with GraphBrain v2.")
