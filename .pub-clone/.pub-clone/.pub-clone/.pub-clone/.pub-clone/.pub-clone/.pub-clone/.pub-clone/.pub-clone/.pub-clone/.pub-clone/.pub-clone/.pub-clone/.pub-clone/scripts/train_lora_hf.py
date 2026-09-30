#!/usr/bin/env python3
"""Trening QLoRA tool-calling ASTRO BEZ unsloth (transformers+peft+trl+bitsandbytes).

Do maszyn, gdzie unsloth nie działa (np. Windows + torch 2.11). Ten sam format danych co
`train_lora_pc.py` (render przez `apply_chat_template` z narzędziami).
"""
import argparse
import json
import os
import sys

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def load_jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="datasets")
    ap.add_argument("--base", default="unsloth/Qwen3-1.7B")
    ap.add_argument("--out", default="out/astro-qwen3-lora")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq-len", type=int, default=4096)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        n = len(load_jsonl(os.path.join(args.data, "astro_train.jsonl")))
        print(f"OK: train={n}")
        return 0

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTTrainer, SFTConfig

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=bnb,
                                                 device_map={"": 0})
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=args.lora_r, lora_alpha=32, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()

    def to_text(ex):
        text = tok.apply_chat_template(ex["messages"], tools=ex.get("tools") or None,
                                       tokenize=False, add_generation_prompt=False)
        if len(tok(text, add_special_tokens=False)["input_ids"]) > args.max_seq_len:
            return None
        return {"text": text}

    tr = [x for x in (to_text(e) for e in load_jsonl(os.path.join(args.data, "astro_train.jsonl"))) if x]
    print(f"w oknie <= {args.max_seq_len}: {len(tr)}", flush=True)
    ds = Dataset.from_list(tr)

    fields = set(getattr(SFTConfig, "__dataclass_fields__", {}).keys())
    kw = dict(output_dir=args.out, num_train_epochs=args.epochs, learning_rate=args.lr,
              per_device_train_batch_size=args.batch,
              gradient_accumulation_steps=args.grad_accum, gradient_checkpointing=True,
              logging_steps=2, save_strategy="no", warmup_ratio=0.03,
              lr_scheduler_type="cosine", bf16=True, optim="adamw_8bit", report_to="none")
    if "max_length" in fields:
        kw["max_length"] = args.max_seq_len
    elif "max_seq_length" in fields:
        kw["max_seq_length"] = args.max_seq_len
    if "dataset_text_field" in fields:
        kw["dataset_text_field"] = "text"
    cfg = SFTConfig(**kw)

    tkw = dict(model=model, args=cfg, train_dataset=ds)
    import inspect
    params = inspect.signature(SFTTrainer.__init__).parameters
    tkw["processing_class" if "processing_class" in params else "tokenizer"] = tok
    trainer = SFTTrainer(**tkw)
    trainer.train()
    os.makedirs(args.out, exist_ok=True)
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print("adapter zapisany:", args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
