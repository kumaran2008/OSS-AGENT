import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TrainingSyncManager:
    """
    Synchronizes local .experience/ datasets and .adapters/ bundles
    to remote GPU training environments or Hugging Face Hub.
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.experience_dir = self.workspace_root / ".experience"
        self.datasets_dir = self.experience_dir / "datasets"
        self.adapters_dir = self.workspace_root / ".adapters"

    def validate_local_assets(self) -> Dict[str, Any]:
        datasets = list(self.datasets_dir.glob("*.jsonl")) if self.datasets_dir.exists() else []
        adapters = [p for p in self.adapters_dir.iterdir() if p.is_dir()] if self.adapters_dir.exists() else []
        return {
            "datasets_found": len(datasets),
            "datasets": [str(d.name) for d in datasets],
            "adapter_roles": [a.name for a in adapters],
            "ready": len(datasets) > 0 or len(adapters) > 0,
        }

    def sync_to_huggingface(
        self,
        repo_id: str,
        token: Optional[str] = None,
        private: bool = True,
        subfolder: str = "datasets",
    ) -> Dict[str, Any]:
        hf_token = token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if not hf_token:
            raise ValueError(
                "Hugging Face token not found. Provide --token or set the HF_TOKEN environment variable."
            )

        try:
            from huggingface_hub import HfApi, create_repo
        except ImportError:
            raise ImportError(
                "huggingface_hub is required for HF sync. Install with: pip install huggingface_hub"
            )

        api = HfApi(token=hf_token)
        print(f"[SyncTool] Creating / verifying Hugging Face repo: {repo_id} (dataset)...")
        create_repo(repo_id=repo_id, token=hf_token, repo_type="dataset", private=private, exist_ok=True)

        if not self.datasets_dir.exists():
            raise FileNotFoundError(f"No datasets directory found at {self.datasets_dir}")

        uploaded_files = []
        for dataset_file in self.datasets_dir.glob("*.jsonl"):
            dest_path = f"{subfolder}/{dataset_file.name}" if subfolder else dataset_file.name
            print(f"[SyncTool] Uploading {dataset_file.name} -> hf://datasets/{repo_id}/{dest_path}...")
            api.upload_file(
                path_or_fileobj=str(dataset_file),
                path_in_repo=dest_path,
                repo_id=repo_id,
                repo_type="dataset",
            )
            uploaded_files.append(dest_path)

        manifest_file = self.adapters_dir / "adapters_manifest.json"
        if manifest_file.exists():
            api.upload_file(
                path_or_fileobj=str(manifest_file),
                path_in_repo="adapters_manifest.json",
                repo_id=repo_id,
                repo_type="dataset",
            )
            uploaded_files.append("adapters_manifest.json")

        return {
            "status": "SUCCESS",
            "target": f"https://huggingface.co/datasets/{repo_id}",
            "uploaded_files": uploaded_files,
        }

    def sync_to_remote_gpu(
        self,
        host: str,
        remote_path: str,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = 22,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        if not shutil.which("rsync"):
            raise RuntimeError("rsync utility is not installed on this system. Install with: pkg install rsync")

        destination_target = f"{user}@{host}:{remote_path}" if user else f"{host}:{remote_path}"

        ssh_opts = f"ssh -p {port}"
        if key_path:
            ssh_opts += f" -i {Path(key_path).expanduser().resolve()}"

        sources = []
        if self.experience_dir.exists():
            sources.append(str(self.experience_dir))
        if self.adapters_dir.exists():
            sources.append(str(self.adapters_dir))

        if not sources:
            raise FileNotFoundError("Neither .experience/ nor .adapters/ found to synchronize.")

        cmd = ["rsync", "-avz", "--progress", "-e", ssh_opts]
        if dry_run:
            cmd.append("--dry-run")
        cmd.extend(sources)
        cmd.append(destination_target)

        print(f"[SyncTool] Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, text=True, capture_output=True)

        if result.returncode != 0:
            print(f"[SyncTool] rsync failed: {result.stderr}", file=sys.stderr)
            return {"status": "FAILED", "returncode": result.returncode, "error": result.stderr}

        print("[SyncTool] Transfer completed successfully.")
        return {"status": "SUCCESS", "destination": destination_target, "sources": sources}

    def dispatch_background_job(
        self,
        host: str,
        remote_path: str,
        role: str,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = 22,
    ) -> Dict[str, Any]:
        """Syncs training assets to PC and launches run_qlora.py in the background."""
        sync_res = self.sync_to_remote_gpu(
            host=host,
            remote_path=remote_path,
            user=user,
            key_path=key_path,
            port=port,
        )
        if sync_res.get("status") != "SUCCESS":
            return sync_res

        target = f"{user}@{host}" if user else host
        ssh_cmd = ["ssh", "-p", str(port)]
        if key_path:
            ssh_cmd.extend(["-i", str(Path(key_path).expanduser().resolve())])

        remote_script = f"{remote_path.rstrip('/')}/.adapters/{role}/run_qlora.py"
        remote_log = f"{remote_path.rstrip('/')}/.adapters/{role}/train.log"

        exec_payload = f"cd {remote_path} && nohup python3 {remote_script} > {remote_log} 2>&1 & echo $!"
        ssh_cmd.extend([target, exec_payload])

        print(f"[SyncTool] Launching background training daemon on {host}...")
        proc = subprocess.run(ssh_cmd, text=True, capture_output=True)

        if proc.returncode == 0:
            pid = proc.stdout.strip()
            print(f"[SyncTool] Training active on PC (PID: {pid}). Logs streaming to {remote_log}")
            return {"status": "RUNNING", "pid": pid, "log_path": remote_log, "host": host}
        else:
            print(f"[SyncTool] Failed to spawn background job: {proc.stderr}")
            return {"status": "FAILED", "error": proc.stderr}


def interactive_sync_prompt():
    """Interactive wizard prompting the user for sync destination."""
    manager = TrainingSyncManager()
    assets = manager.validate_local_assets()

    if not assets["ready"]:
        print("[SyncTool] No staged datasets or adapters found to synchronize.")
        return

    print("\n" + "=" * 55)
    print("      OSS-AGENT TRAINING DATASET SYNC WIZARD")
    print("=" * 55)
    print(f"Staged datasets: {assets['datasets_found']} file(s)")
    print(f"Staged adapters: {len(assets['adapter_roles'])} role(s)\n")
    print("Choose how you would like to offload this training data:")
    print("  [1] Hugging Face Hub (Recommended: zero RAM, free cloud storage, Colab-ready)")
    print("  [2] Remote GPU Host / PC (Sync & run training in background)")
    print("  [3] Keep local only (Skip sync)")

    try:
        choice = input("\nSelect an option [1-3] (default: 1): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nSync skipped.")
        return

    if choice in ("", "1"):
        repo_id = input("Enter HF dataset repo (e.g. username/oss-agent-data): ").strip()
        if not repo_id:
            print("Aborted: Repo ID is required for Hugging Face sync.")
            return

        token = os.environ.get("HF_TOKEN")
        if not token:
            token = input("Enter Hugging Face Token (leave empty if saved in env): ").strip() or None

        is_public = input("Make dataset public? [y/N] (default: Private): ").strip().lower() == "y"

        try:
            res = manager.sync_to_huggingface(repo_id=repo_id, token=token, private=not is_public)
            print(f"\nUpload complete! Dataset live at: {res['target']}")
        except Exception as e:
            print(f"\nHugging Face sync failed: {e}")

    elif choice == "2":
        host = input("Enter PC IP address (e.g. 192.168.1.50): ").strip()
        if not host:
            print("Aborted: Host is required.")
            return
        user = input("Enter PC SSH username: ").strip() or None
        remote_path = input("Enter path to oss-agent folder on PC: ").strip()
        if not remote_path:
            print("Aborted: Path is required.")
            return
        key = input("SSH private key path (leave blank for default): ").strip() or None

        role = "mason_backend_mason"
        if assets["adapter_roles"]:
            role = assets["adapter_roles"][0]

        try:
            res = manager.dispatch_background_job(
                host=host,
                remote_path=remote_path,
                role=role,
                user=user,
                key_path=key,
            )
            if res.get("status") == "RUNNING":
                print(f"\nBackground training successfully started on {host}!")
                print("Monitor live output anytime with:")
                user_prefix = f"{user}@" if user else ""
                log_file = res.get("log_path", "")
                print(f"  ssh {user_prefix}{host} 'tail -f {log_file}'")
        except Exception as e:
            print(f"\nRemote execution failed: {e}")

    elif choice == "3":
        print("Data retained locally in .experience/ and .adapters/.")
    else:
        print("Invalid option selected. Sync skipped.")


def main():
    parser = argparse.ArgumentParser(description="Synchronize oss-agent training datasets & adapter bundles.")
    subparsers = parser.add_subparsers(dest="action", help="Target sync backend")

    subparsers.add_parser("status", help="Inspect local datasets and adapter staging state.")

    hf_parser = subparsers.add_parser("hf", help="Upload datasets to Hugging Face Hub")
    hf_parser.add_argument("--repo-id", required=True, help="HF Dataset repository (e.g. username/oss-agent-dataset)")
    hf_parser.add_argument("--token", help="Hugging Face User Access Token (or set HF_TOKEN)")
    hf_parser.add_argument("--public", action="store_true", help="Set repository visibility to public")

    remote_parser = subparsers.add_parser("remote", help="Sync to remote GPU server via rsync/ssh")
    remote_parser.add_argument("--host", required=True, help="Remote host IP or domain")
    remote_parser.add_argument("--path", required=True, help="Destination directory path on remote server")
    remote_parser.add_argument("--user", help="Remote SSH user")
    remote_parser.add_argument("--key", help="Path to SSH private key identity")
    remote_parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    remote_parser.add_argument("--dry-run", action="store_true", help="Run in trial mode without copying files")

    args = parser.parse_args()

    if len(sys.argv) == 1:
        interactive_sync_prompt()
        return

    if args.action == "status":
        manager = TrainingSyncManager()
        state = manager.validate_local_assets()
        print("\n--- [Local Training Asset State] ---")
        print(f"  • Datasets available: {state['datasets_found']} -> {state['datasets']}")
        print(f"  • Staged Adapters: {len(state['adapter_roles'])} roles -> {state['adapter_roles']}")
        print(f"  • Ready for sync: {state['ready']}\n")
        return

    manager = TrainingSyncManager()
    if args.action == "hf":
        res = manager.sync_to_huggingface(
            repo_id=args.repo_id,
            token=args.token,
            private=not args.public,
        )
        print(f"\n[Done] Upload complete: {res['target']}")

    elif args.action == "remote":
        res = manager.sync_to_remote_gpu(
            host=args.host,
            remote_path=args.path,
            user=args.user,
            key_path=args.key,
            port=args.port,
            dry_run=args.dry_run,
        )
        if res["status"] == "SUCCESS":
            print(f"\n[Done] Successfully synced to {res['destination']}")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
