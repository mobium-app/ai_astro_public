# Show HN — treść postu (2026-09-29)

## Tytuł (HN)
Show HN: ASTRO — self-improving voice AI agent for Raspberry Pi + Hailo NPU (offline-first)

## Body (HN, ~3-4 akapity)
I built a voice AI agent that lives entirely on a Raspberry Pi 5 with a Hailo-10H
NPU — it wakes on a Polish wake word ("Hej Astro"), transcribes speech (Whisper
on NPU), speaks back (Piper TTS), sees its surroundings (IP camera: YOLO object
detection + face recognition + OCR + age/gender on NPU), and executes system
commands offline. No cloud required.

The interesting part: it improves itself. It runs a knowledge loop (asks a local
11B teacher on a LAN GPU PC, stores answers in a vector DB), distills trajectories,
and fine-tunes its own LoRA adapters (Qwen3-1.7B) — promoted to production only
after passing quality gates (tools/chain/chat benchmarks vs baseline).

Architecture: clean micro-MVC agent SDK, ~990 hermetic unit tests (stdlib only),
safety rules (commands never leave the device), deterministic voice-command
recipes without the model. Works without NPU/camera/GPU too (CPU fallbacks +
simulations).

MIT licensed. PRs welcome — there are good-first-issue tasks labeled in the repo.

Links:
- Repo: https://github.com/mobium-app/ai_astro_public
- Demo (terminal): https://github.com/mobium-app/ai_astro_public/blob/main/assets/astro_demo.gif
- Voice sample: https://github.com/mobium-app/ai_astro_public/blob/main/assets/astro_voice_sample.wav

## Warianty dla Reddit
### r/selfhosted
Title: I built a self-improving voice AI agent that runs fully offline on a Raspberry Pi 5 + Hailo NPU

### r/LocalLLaMA
Title: Self-improving LoRA pipeline on edge hardware: Raspberry Pi agent fine-tunes its own Qwen3-1.7B adapters (MIT, open source)

### r/Raspberry_Pi
Title: Voice AI assistant with Hailo-10H NPU: STT, vision, and self-training LoRA on a Pi 5

## Wykop / mirko (PL)
Title: Napisałem agenta głosowego, który uczy się sam — działa w całości na Raspberry Pi 5 + Hailo (offline). MIT, open source.