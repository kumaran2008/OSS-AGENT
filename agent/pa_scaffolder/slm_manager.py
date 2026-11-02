import os
import urllib.request
from pathlib import Path
from typing import Tuple


class SLMScaffolder:
    """
    Automated Downloader and Scaffolder for Compact Edge Reasoning Models.
    Default: Qwen 2.5 0.5B Instruct (Q4_K_M GGUF, 398MB).
    Alternative: DeepSeek-R1-Distill-Qwen-1.5B (Q4_K_M GGUF, 1.1GB).
    """

    MODEL_REGISTRY = {
        "qwen2.5_0.5b": {
            "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "size_mb": 398,
            "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        },
        "deepseek_r1_1.5b": {
            "filename": "deepseek-r1-distill-qwen-1.5b-q4_k_m.gguf",
            "size_mb": 1110,
            "url": "https://huggingface.co/unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf"
        }
    }

    def __init__(self, target_dir: Path = Path("workspace/models/slm")):
        self.target_dir = Path(target_dir)
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def is_model_installed(self, model_key: str = "qwen2.5_0.5b") -> bool:
        meta = self.MODEL_REGISTRY.get(model_key)
        if not meta:
            return False
        model_path = self.target_dir / meta["filename"]
        return model_path.exists() and model_path.stat().st_size > 1024 * 1024 * 10

    def ensure_slm_scaffolded(self, model_key: str = "qwen2.5_0.5b") -> Tuple[bool, Path]:
        """
        Verifies local model presence; downloads it if missing.
        """
        meta = self.MODEL_REGISTRY.get(model_key, self.MODEL_REGISTRY["qwen2.5_0.5b"])
        model_path = self.target_dir / meta["filename"]

        if model_path.exists() and model_path.stat().st_size > 1024 * 1024 * 10:
            return True, model_path

        print(f"\n[SLM Scaffolder] Downloading compact reasoning model ({meta['filename']} - ~{meta['size_mb']}MB)...")
        try:
            def _progress(count, block_size, total_size):
                if total_size > 0:
                    pct = int(count * block_size * 100 / total_size)
                    print(f"\r • Progress: {pct}% complete...", end="", flush=True)

            urllib.request.urlretrieve(meta["url"], str(model_path), reporthook=_progress)
            print(f"\n[SLM Scaffolder] Model ready at: {model_path}")
            return True, model_path
        except Exception as e:
            print(f"\n[SLM Scaffolder] Download failed ({e}). Fallback to built-in episodic SLM.")
            return False, model_path
