import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from tools.system_tier import CURRENT_TIER, HardwareTier


def get_tier_label() -> str:
    return getattr(CURRENT_TIER, "name", str(CURRENT_TIER))


def is_high_tier() -> bool:
    high_marker = getattr(HardwareTier, "TIER_HIGH", "high")
    return CURRENT_TIER == high_marker or str(CURRENT_TIER).lower() in ("high", "tier_high")


class QLoRAPipeline:
    """
    Prepares and dispatches QLoRA fine-tuning jobs.
    Configures 4-bit NF4 quantization, gradient checkpointing, and target projection layers.
    """

    DEFAULT_BASE_MODEL = "meta-llama/Llama-3.2-3B-Instruct"

    def __init__(self, output_root: str = ".adapters"):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def generate_training_script(
        self,
        role: str,
        dataset_path: Path,
        base_model: Optional[str] = None,
        epochs: int = 3,
        batch_size: int = 1,
        lora_r: int = 16,
        lora_alpha: int = 32,
    ) -> Path:
        role_dir = self.output_root / role
        role_dir.mkdir(parents=True, exist_ok=True)
        script_path = role_dir / "run_qlora.py"
        model_name = base_model or self.DEFAULT_BASE_MODEL

        script_content = f'''# Auto-generated QLoRA training harness for role: {role}
import os
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

MODEL_ID = "{model_name}"
DATASET_PATH = "{dataset_path.resolve()}"
OUTPUT_DIR = "{role_dir.resolve()}"

print(f"[QLoRA Engine] Starting training for role '{role}' on base model: {{MODEL_ID}}")

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

device_map = "auto" if torch.cuda.is_available() else "cpu"
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config if torch.cuda.is_available() else None,
    device_map=device_map,
    trust_remote_code=True,
)

if torch.cuda.is_available():
    model = prepare_model_for_kbit_training(model)

lora_config = LoraConfig(
    r={lora_r},
    lora_alpha={lora_alpha},
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size={batch_size},
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    num_train_epochs={epochs},
    logging_steps=5,
    save_strategy="epoch",
    fp16=torch.cuda.is_available(),
    report_to="none",
)

dataset = load_dataset("json", data_files=DATASET_PATH, split="train")

def format_prompts(batch):
    formatted = []
    for conv in batch["messages"]:
        text = tokenizer.apply_chat_template(conv, tokenize=False)
        formatted.append(text)
    return {{"text": formatted}}

dataset = dataset.map(format_prompts, batched=True)

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=2048,
    tokenizer=tokenizer,
    args=training_args,
)

print("[QLoRA Engine] Executing optimizer steps...")
trainer.train()

final_adapter_path = os.path.join(OUTPUT_DIR, "final_adapter")
model.save_pretrained(final_adapter_path)
tokenizer.save_pretrained(final_adapter_path)
print(f"[QLoRA Engine] Successfully saved adapter at: {{final_adapter_path}}")
'''
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        return script_path

    def dispatch_training_job(self, role: str, dataset_path: Path) -> Dict[str, Any]:
        script_path = self.generate_training_script(role, dataset_path)
        role_dir = self.output_root / role

        if is_high_tier():
            print(f"[QLoRA] High-tier hardware detected. Executing {script_path.name}...")
            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
                success = proc.returncode == 0
                return {
                    "status": "COMPLETED" if success else "FAILED",
                    "role": role,
                    "adapter_dir": str(role_dir / "final_adapter"),
                    "log": proc.stdout[-500:] if success else proc.stderr[-500:],
                }
            except Exception as e:
                return {"status": "ERROR", "role": role, "error": str(e)}

        tier_name = get_tier_label()
        print(f"[QLoRA] Device tier ({tier_name}): Staged training bundle at {role_dir}.")
        return {
            "status": "STAGED",
            "role": role,
            "adapter_dir": str(role_dir / "final_adapter"),
            "script_path": str(script_path),
            "dataset_path": str(dataset_path),
            "instructions": f"Run 'python3 {script_path}' on a GPU-enabled host.",
        }
