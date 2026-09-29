# Faza 4 — upgrade HailoRT 5.1.1 -> 5.3.0 (Hailo-10H, AI HAT+ 2)

> Zgoda użytkownika: 2026-09-28. Cel: nowszy gen-ai model zoo z VLM (Qwen2-VL/3-VL 2B) → offline
> opis sceny na NPU. Ryzyko: sterownik/NPU/STT. Backup i rollback przygotowane.

## Stan wyjściowy (backup)
- `~/astro-backups/hailo-5.1.1/`: `packages_list.txt`, `fw_before.txt` + `.deb` (h10-hailort,
  h10-hailort-pcie-driver, python3-h10-hailort). `hailo-gen-ai-model-zoo` 5.1.1 nie jest w repo Pi
  (instalowany lokalnie) — odtworzenie: reinstalacja pakietu 5.1.x z archiwum lub powrót do zoo.
- Firmware przed: 5.1.1, HAILO10H. `/dev/hailo0`. STT (Whisper-Base.hef) w `scripts/astro_voice.py`.

## Kroki
1. Zatrzymać usługi używające NPU: `astro-voice`/`astro.service` (STT), `astro-vision-*` nie używają.
2. Pobrać z Hailo Developer Zone (wymaga logowania — manualny download użytkownika):
   - `hailort_5.3.0_arm64.deb`
   - `hailort-pcie-driver_5.3.0_all.deb`
   - `hailo_gen_ai_model_zoo_5.3.0_arm64.deb`
   - `hailo-tappas-core_5.3.0_arm64.deb` (opcjonalnie, dla pipeline'ów)
   - PyHailoRT `.whl` (Python 3.13, aarch64)
3. Odinstalować stare: `apt remove h10-hailort-pcie-driver hailo-gen-ai-model-zoo h10-hailort`
   (usuwa też `python3-h10-hailort`).
4. `dpkg -i` nowych pakietów + `.whl`; reboot (sterownik PCIe).
5. `hailortcli fw-control identify` → 5.3.0; `git clone hailo-ai/hailo-apps` + `install.sh`.
6. Pobrać HEF-y gen-ai (VLM `vlm_chat`), sprawdzić współistnienie ze STT (jedno VDevice).

## Bramka „GO/NO-GO"
- GO dopiero po pobraniu pakietów 5.3.0 (wymaga konta Hailo). Bez plików nie ruszamy 5.1.1.

## Rollback (gdy STT/NPU padnie)
```bash
sudo systemctl stop astro.service astro-voice.service 2>/dev/null
cd ~/astro-backups/hailo-5.1.1
sudo dpkg -i h10-hailort_5.1.1_arm64.deb h10-hailort-pcie-driver_5.1.1_all.deb python3-h10-hailort_5.1.1-1_arm64.deb
# hailo-gen-ai-model-zoo: reinstalacja 5.1.x (archiwum) LUB pozostaw nowy, jeśli zgodny
sudo systemctl restart astro.service
hailortcli fw-control identify    # ma być 5.1.1
```

## Status
- [x] Backup 5.1.1 + plan rollbacku
- [x] Pakiety 5.3.0 z Hailo Developer Zone (pobrane przez konto)
- [x] Pierwsza próba — **NIEUDANA** na kernelu 6.18.50 (sterownik `vdma/monitor.c`); rollback do 5.1.1.
- [x] **Druga próba — UDANA**: kernel **6.12.75+rpt-rpi-2712**, sterownik 5.3.0 kompiluje się;
      `hailortcli` → FW 5.3.0; węzeł `/dev/h1x-0`; STT i VLM działają. Szczegóły: `HAILO_GATE.md`.
- [x] HEF `Qwen2-VL-2B-Instruct.hef` pobrany z walidacją rozmiaru (`scripts/fetch_hailo_vlm.sh`).
- [x] Integracja VLM w ASTRO (NPU in-process, fallback do Ollama) + testy.
- Rollback: `scripts/hailo_rollback_5.1.1.sh` (pakiety) + backup kernela w `~/astro-backups/`.
