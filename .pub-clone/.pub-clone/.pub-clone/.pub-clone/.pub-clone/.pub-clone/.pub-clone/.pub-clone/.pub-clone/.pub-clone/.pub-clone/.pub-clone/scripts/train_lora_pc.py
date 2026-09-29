#!/usr/bin/env python3
"""E6/Faza D — trening QLoRA na PC z GPU (NIE na Raspberry Pi).

Destylacja tool-callingu: dane `datasets/astro_{train,val}.jsonl` (format
`{"messages":[...], "tools":[schemas]}` z `scripts/build_dataset.py`) -> LoRA na bazie
Qwen3-1.7B. Dane renderujemy `tokenizer.apply_chat_template(messages, tools=...)`, więc model
uczy się DOKŁADNIE formatu wywołań, którego używa runtime ASTRO + Ollama.

Uruchamiane na PC (Kali, RTX 4060 8 GB) w venv z unsloth:
    ~/atena-lora/.venv-unsloth/bin/python astro_train/train_lora_pc.py \
        --data astro_train --base unsloth/Qwen3-1.7B --out out/astro-qwen3-lora --smoke

Eksport do Ollamy (na PC):
    ... train_lora_pc.py ... --merge --gguf q4_k_m
    # -> out/astro-qwen3-lora-gguf/*.gguf  (skopiuj na Pi i `ollama create`)
"""

import argparse
import json
import os
import sys

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("WANDB_DISABLED", "true")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def check_dataset(data_dir, train_name="astro_train.jsonl", val_name="astro_val.jsonl"):
    tr = os.path.join(data_dir, train_name)
    va = os.path.join(data_dir, val_name)
    if not os.path.exists(tr):
        print(f"BŁĄD: brak {tr} (uruchom scripts/build_dataset.py)")
        return 1
    n = 0
    chars = 0
    with_tools = 0
    for ex in load_jsonl(tr):
        msgs = ex.get("messages") or []
        assert msgs and msgs[-1]["role"] == "assistant", "ostatnia wiadomość != assistant"
        n += 1
        chars = max(chars, sum(len(str(m.get("content") or "")) for m in msgs))
        if ex.get("tools"):
            with_tools += 1
    nval = len(load_jsonl(va)) if os.path.exists(va) else 0
    print(f"OK: train={n} (z tools={with_tools}), val={nval}, najdłuższy ~{chars} znaków")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Trening LoRA tool-calling ASTRO (PC/GPU)")
    ap.add_argument("--data", default="datasets", help="katalog z astro_train.jsonl/astro_val.jsonl")
    ap.add_argument("--base", default="unsloth/Qwen3-1.7B")
    ap.add_argument("--out", default="out/astro-qwen3-lora")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq-len", type=int, default=4096)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--save-steps", type=int, default=50)
    ap.add_argument("--max-steps", type=int, default=-1, help="limit kroków (smoke); -1 = pełny")
    ap.add_argument("--no-eval", action="store_true")
    ap.add_argument("--offload-optim", action="store_true",
                    help="trzymaj stan optymalizatora w RAM (oszczędza ~0.5-1 GB VRAM; "
                         "chroni przed OOM, gdy obok działa Ollama/nauczyciel)")
    ap.add_argument("--early-stopping", type=int, default=0,
                    help="cierpliwość early-stop na eval_loss (0 = wyłączone)")
    ap.add_argument("--eval-batch", type=int, default=1, help="per_device_eval_batch_size (oszczędnie)")
    ap.add_argument("--merge", action="store_true", help="zapisz scalony model 16-bit")
    ap.add_argument("--gguf", default="", help="eksport GGUF o tej kwantyzacji, np. q4_k_m")
    ap.add_argument("--check", action="store_true", help="tylko walidacja danych (bez GPU)")
    args = ap.parse_args()

    if args.check:
        return check_dataset(args.data)

    import torch
    from datasets import Dataset
    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig

    bf16 = bool(torch.cuda.is_bf16_supported())
    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_seq_len, dtype=None, load_in_4bit=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = FastLanguageModel.get_peft_model(
        model, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        bias="none", use_gradient_checkpointing="unsloth", random_state=3407)
    model.print_trainable_parameters()

    def to_text(ex):
        text = tok.apply_chat_template(ex["messages"], tools=ex.get("tools") or None,
                                       tokenize=False, add_generation_prompt=False)
        if len(tok(text, add_special_tokens=False)["input_ids"]) > args.max_seq_len:
            return None
        return {"text": text}

    train = load_jsonl(os.path.join(args.data, "astro_train.jsonl"))
    val_path = os.path.join(args.data, "astro_val.jsonl")
    val = load_jsonl(val_path) if os.path.exists(val_path) else []
    tr = [x for x in (to_text(e) for e in train) if x]
    va = [x for x in (to_text(e) for e in val) if x]
    print(f"w oknie <= {args.max_seq_len}: train {len(tr)}/{len(train)}, val {len(va)}/{len(val)}",
          flush=True)
    ds_tr = Dataset.from_list(tr)
    ds_va = Dataset.from_list(va) if va else None

    fields = set(getattr(SFTConfig, "__dataclass_fields__", {}).keys())
    kw = dict(output_dir=args.out, num_train_epochs=args.epochs, learning_rate=args.lr,
              per_device_train_batch_size=args.batch,
              gradient_accumulation_steps=args.grad_accum, gradient_checkpointing=True,
              logging_steps=2, save_steps=args.save_steps, save_total_limit=2,
              warmup_ratio=0.03, lr_scheduler_type="cosine", bf16=bf16, fp16=not bf16,
              optim="adamw_8bit", report_to="none")
    if args.offload_optim:
        kw["optim"] = "paged_adamw_8bit"
    if "max_seq_length" in fields:
        kw.update(max_seq_length=args.max_seq_len, dataset_text_field="text", packing=False)
    if args.max_steps and args.max_steps > 0:
        kw["max_steps"] = args.max_steps
    if ds_va is not None and not args.no_eval:
        kw["eval_strategy" if "eval_strategy" in fields else "evaluation_strategy"] = "steps"
        kw["eval_steps"] = args.save_steps
        kw["per_device_eval_batch_size"] = args.eval_batch
        kw["eval_accumulation_steps"] = 1
        kw["prediction_loss_only"] = True
        kw["bf16_full_eval"] = bf16
        kw["fp16_full_eval"] = not bf16
    if args.early_stopping and args.early_stopping > 0 and ds_va is not None and not args.no_eval:
        kw["save_strategy"] = "steps"
        kw["load_best_model_at_end"] = True
        kw["metric_for_best_model"] = "eval_loss"
        kw["greater_is_better"] = False
    cfg = SFTConfig(**kw)

    import inspect
    params = inspect.signature(SFTTrainer.__init__).parameters
    tkw = dict(model=model, args=cfg, train_dataset=ds_tr)
    if ds_va is not None:
        tkw["eval_dataset"] = ds_va
    tkw["processing_class" if "processing_class" in params else "tokenizer"] = tok
    if args.early_stopping and args.early_stopping > 0 and ds_va is not None and not args.no_eval:
        from transformers import EarlyStoppingCallback
        tkw["callbacks"] = [EarlyStoppingCallback(early_stopping_patience=args.early_stopping)]
        print(f"early-stop: patience={args.early_stopping} (eval_loss, eval/save co "
              f"{args.save_steps} kroków)", flush=True)
    trainer = SFTTrainer(**tkw)
    trainer.train()
    if getattr(trainer.state, "best_metric", None) is not None:
        metric = getattr(trainer.args, "metric_for_best_model", "eval_loss")
        print(f"best {metric}: {trainer.state.best_metric} "
              f"(checkpoint {trainer.state.best_model_checkpoint})", flush=True)
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"adapter zapisany: {args.out}")

    if args.merge:
        mdir = args.out + "-merged"
        model.save_pretrained_merged(mdir, tok, save_method="merged_16bit")
        print(f"scalony model: {mdir}")

    if args.gguf:
        gdir = args.out + "-gguf"
        model.save_pretrained_gguf(gdir, tok, quantization_method=args.gguf)
        print(f"GGUF: {gdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
