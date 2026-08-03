"""Pinned LLM artifacts for room_config (ADR-005 + ADR-006).

Default model remains Qwen2.5-0.5B (ADR-005). Catalog of selectable
models is ADR-006. Do not invent hashes — recompute with Get-FileHash
or take Hugging Face LFS OID (SHA256 of blob) from the tree API.
"""

ALLOWED_DOMAINS = [
    "github.com",
    "objects.githubusercontent.com",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
]

# llama.cpp b10216 Windows CPU x64
RUNTIME_ID = "llama.cpp-b10216-win-cpu-x64"
RUNTIME_URL = (
    "https://github.com/ggml-org/llama.cpp/releases/download/"
    "b10216/llama-b10216-bin-win-cpu-x64.zip"
)
RUNTIME_SHA256 = (
    "CA78DF53654BE907193F2615F590C51960F0A009C09285D1D1A5EFA8B84D69B9"
)
LLAMA_SERVER_EXE_SHA256 = (
    "DCC76B45556B0252B353A4693E84376C8A04D2EB44B5BF153EFC18A5556C54E6"
)
LLAMA_SERVER_IMPL_DLL_SHA256 = (
    "9CC77AC1DE3F90B3BEFA47377BB578EE3E3E3979DF8B39C5EBBC92B92193C513"
)

# Default (ADR-005)
DEFAULT_MODEL_ID = "qwen2.5-0.5b-instruct-q4_k_m"

# Backward-compat aliases used by older tests / imports
MODEL_ID = DEFAULT_MODEL_ID
MODEL_URL = (
    "https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/"
    "resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
)
MODEL_SHA256 = (
    "6EB923E7D26E9CEA28811E1A8E852009B21242FB157B26149D3B188F3A8C8653"
)

# Catalog — product dropdown (ADR-006). SHA256 uppercase for consistency.
MODEL_CATALOG: dict[str, dict] = {
    "qwen2.5-0.5b-instruct-q4_k_m": {
        "display": "Qwen2.5-0.5B-Instruct",
        "params_b": 0.49,
        "filename": "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/"
            "resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
        ),
        "sha256": (
            "6EB923E7D26E9CEA28811E1A8E852009B21242FB157B26149D3B188F3A8C8653"
        ),
        "approx_size_gb": 0.4,
    },
    "qwen3-0.6b-q4_k_m": {
        "display": "Qwen3-0.6B",
        "params_b": 0.6,
        "filename": "Qwen3-0.6B-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/"
            "resolve/main/Qwen3-0.6B-Q4_K_M.gguf"
        ),
        "sha256": (
            "AC2D97712095A558E31573F62F466A3F9D93990898B0EC79D7C974C1780D524A"
        ),
        "approx_size_gb": 0.4,
    },
    "qwen3.5-2b-q4_k_m": {
        "display": "Qwen3.5-2B",
        "params_b": 2.0,
        "filename": "Qwen_Qwen3.5-2B-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/"
            "resolve/main/Qwen_Qwen3.5-2B-Q4_K_M.gguf"
        ),
        # HF LFS OID = SHA256 of blob (tree API, 2026-08-01)
        "sha256": (
            "57A1085840F497D764A7FC5D346922DBDE961EFB54CC792EA81D694FD846A1D8"
        ),
        "approx_size_gb": 1.4,
    },
    "gemma-4-e2b-it-q4_k_m": {
        "display": "Gemma 4 E2B",
        "params_b": 2.3,
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/"
            "resolve/main/gemma-4-E2B-it-Q4_K_M.gguf"
        ),
        # HF LFS OID = SHA256 of blob (tree API, 2026-08-01)
        "sha256": (
            "740185B21D22CEB83A11C3AA62AD5842EF32C70F6096D756BBEE85A1E4EC34B8"
        ),
        "approx_size_gb": 3.1,
    },
}


class UnknownModelError(ValueError):
    """model_id không nằm trong catalog."""


def list_models() -> list[dict]:
    """Danh sách catalog cho GET /api/models (không lộ hash đầy đủ là OK)."""
    out = []
    for mid, m in MODEL_CATALOG.items():
        out.append({
            "model_id": mid,
            "display": m["display"],
            "params_b": m["params_b"],
            "filename": m["filename"],
            "approx_size_gb": m["approx_size_gb"],
            "is_default": mid == DEFAULT_MODEL_ID,
        })
    return out


def get_model(model_id: str | None = None) -> dict:
    # Chỉ fallback khi None; "" / khoảng trắng → UnknownModelError
    if model_id is None:
        mid = DEFAULT_MODEL_ID
    else:
        mid = str(model_id).strip()
        if not mid:
            raise UnknownModelError("empty model_id")
    if mid not in MODEL_CATALOG:
        raise UnknownModelError(f"unknown model_id: {mid}")
    return dict(MODEL_CATALOG[mid], model_id=mid)


def room_config_llm(threshold_c: float = 75.0, site_id: str = "local",
                    max_concurrent: int = 1,
                    telemetry_interval_s: float = 2.0,
                    model_id: str | None = None,
                    model_generation: int = 0) -> dict:
    m = get_model(model_id)
    return {
        "model_id": m["model_id"],
        "model_url": m["url"],
        "model_sha256": m["sha256"],
        "model_filename": m["filename"],
        "model_generation": int(model_generation),
        "runtime_url": RUNTIME_URL,
        "runtime_sha256": RUNTIME_SHA256,
        "runtime_id": RUNTIME_ID,
        "llama_server_exe_sha256": LLAMA_SERVER_EXE_SHA256,
        "llama_server_impl_dll_sha256": LLAMA_SERVER_IMPL_DLL_SHA256,
        "allowed_domains": list(ALLOWED_DOMAINS),
        "threshold_c": threshold_c,
        "site_id": site_id,
        "max_concurrent": max_concurrent,
        "telemetry_interval_s": telemetry_interval_s,
    }
