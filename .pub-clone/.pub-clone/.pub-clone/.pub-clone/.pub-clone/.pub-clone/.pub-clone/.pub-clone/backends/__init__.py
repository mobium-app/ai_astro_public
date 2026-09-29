"""Warstwa backendów LLM: npu | cpu | pc(opt-in) | remote(opt-in)."""

from .base import Backend, BackendResult
from . import modes
from .cpu import CpuBackend
from .npu import (NpuBackend, NpuEngine, NPU_ENGINE, available_hefs, device_busy,
                  device_holders, device_paths, device_present, firmware_version,
                  hailo_platform_available, npu_status, npu_status_text,
                  resolve_npu_llm_hef, resolve_vlm_hef)
from .remote import RemoteBackend
from .telemetry import NPU_TELEMETRY, NpuTelemetry
from .registry import (BackendRegistry, POLICY, REASONS, build_default, choose, choose_detail,
                       run, set_default, DEFAULT, model_for, mode_for, policy_table)

__all__ = ["Backend", "BackendResult", "CpuBackend", "NpuBackend", "NpuEngine", "NPU_ENGINE",
           "hailo_platform_available", "resolve_npu_llm_hef", "resolve_vlm_hef", "device_present",
           "device_paths", "device_holders",
           "device_busy", "firmware_version", "available_hefs", "npu_status", "npu_status_text",
           "RemoteBackend", "BackendRegistry", "POLICY", "REASONS", "build_default", "choose",
           "choose_detail", "run", "set_default", "DEFAULT", "NPU_TELEMETRY", "NpuTelemetry",
           "model_for", "mode_for", "policy_table", "modes"]
