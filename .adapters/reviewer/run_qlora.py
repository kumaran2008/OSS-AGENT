# Auto-generated QLoRA training harness for role: reviewer
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

MODEL_ID = "meta-llama/Llama-3.2-3B-Instruct"
DATASET_PATH = "/data/data/com.termux/files/home/oss-agent/.experience/datasets/reviewer_sft.jsonl"
OUTPUT_DIR = "/data/data/com.termux/files/home/oss-agent/.adapters/reviewer"

print(f"[QLoRA Engine] Starting training for role 'reviewer' on base model: {MODEL_ID}")

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
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    num_train_epochs=3,
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
    return {"text": formatted}

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
print(f"[QLoRA Engine] Successfully saved adapter at: {final_adapter_path}")
