import argparse
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path regardless of execution working directory
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.training.adapter_registry import adapter_registry


def pull_adapter_from_hf(
    repo_id: str,
    role: str,
    token: str = None,
    base_model: str = "meta-llama/Llama-3.2-3B-Instruct",
) -> Path:
    """Downloads adapter repository from Hugging Face Hub into local .adapters/."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[Error] huggingface_hub is required. Install via: pip install huggingface_hub")
        sys.exit(1)

    hf_token = token or os.environ.get("HF_TOKEN")
    dest_dir = Path(f".adapters/{role}/final_adapter").resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"[PullAdapter] Downloading '{repo_id}' -> {dest_dir}...")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(dest_dir),
        token=hf_token,
        ignore_patterns=["*.msgpack", "*.h5", "*.ot"],
    )

    # Register in central adapters_manifest.json
    record = adapter_registry.register_adapter(
        role=role,
        adapter_path=str(dest_dir),
        base_model=base_model,
        benchmark_score=1.0,
        training_samples=0,
        metadata={"source": "huggingface", "repo_id": repo_id},
    )

    print(f"[PullAdapter] Registered adapter for role '{role}' in manifest:")
    print(f"  • Path: {record['adapter_path']}")
    print(f"  • Base Model: {record['base_model']}")
    return dest_dir


def main():
    parser = argparse.ArgumentParser(description="Pull trained LoRA adapter weights from Hugging Face.")
    parser.add_argument("--repo-id", required=True, help="HF adapter repository (e.g. username/oss-agent-mason-adapter)")
    parser.add_argument("--role", required=True, help="Agent role name (e.g. mason_backend_mason, reviewer, tester)")
    parser.add_argument("--token", help="Hugging Face read token (defaults to HF_TOKEN environment variable)")
    parser.add_argument("--base-model", default="meta-llama/Llama-3.2-3B-Instruct", help="Base model identifier")

    args = parser.parse_args()
    pull_adapter_from_hf(
        repo_id=args.repo_id,
        role=args.role,
        token=args.token,
        base_model=args.base_model,
    )


if __name__ == "__main__":
    main()
