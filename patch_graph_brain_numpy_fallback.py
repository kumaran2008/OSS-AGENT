from pathlib import Path

target = Path("agent/pa_scaffolder/graph_brain.py")
code = target.read_text(encoding="utf-8")

old_embed = """    @classmethod
    def embed_text(cls, text: str) -> np.ndarray:
        # Check if local ONNX embedding model exists
        onnx_model_path = Path("workspace/models/embeddings/bge-small-en.onnx")
        if onnx_model_path.exists():
            try:
                import onnxruntime as ort
                # Load and run ONNX session if available
                # (Omitted here for zero-dep fallback safety)
                pass
            except Exception:
                pass

        # High-performance deterministic semantic feature hashing
        tokens = text.lower().strip().split()
        if not tokens:
            return np.zeros(cls.DIM, dtype=np.float32)

        vec = np.zeros(cls.DIM, dtype=np.float32)

        # Word shingles and n-grams
        for i, word in enumerate(tokens):
            # Unigram hash
            h1 = int(hashlib.md5(word.encode('utf-8')).hexdigest()[:8], 16) % cls.DIM
            vec[h1] += 1.0

            # Bigram shingle
            if i < len(tokens) - 1:
                bigram = f"{word}_{tokens[i+1]}"
                h2 = int(hashlib.sha256(bigram.encode('utf-8')).hexdigest()[:8], 16) % cls.DIM
                vec[h2] += 1.5

        # Normalize to unit sphere (L2 norm) for cosine similarity dot product
        norm = np.linalg.norm(vec)
        if norm > 1e-9:
            vec = vec / norm
        return vec.astype(np.float32)"""

new_embed = """    @classmethod
    def embed_text(cls, text: str):
        tokens = text.lower().strip().split()
        dim = cls.DIM
        vec = [0.0] * dim
        if not tokens:
            return vec

        for i, word in enumerate(tokens):
            h1 = int(hashlib.md5(word.encode('utf-8')).hexdigest()[:8], 16) % dim
            vec[h1] += 1.0
            if i < len(tokens) - 1:
                bigram = f"{word}_{tokens[i+1]}"
                h2 = int(hashlib.sha256(bigram.encode('utf-8')).hexdigest()[:8], 16) % dim
                vec[h2] += 1.5

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-9:
            vec = [x / norm for x in vec]

        try:
            import numpy as np
            return np.array(vec, dtype=np.float32)
        except ImportError:
            import array
            return array.array('f', vec)"""

# Handle numpy import at top
code = code.replace("import numpy as np", "try:\n    import numpy as np\nexcept ImportError:\n    pass")
if old_embed in code:
    code = code.replace(old_embed, new_embed)

target.write_text(code, encoding="utf-8")
print("[✓] Patched graph_brain.py for zero-dependency execution.")
