"""Embed chunk text with sentence-transformers/all-MiniLM-L6-v2 (384-dim).

Runs the model's official ONNX export with onnxruntime instead of PyTorch: on this
machine Windows Application Control blocks torch's DLLs. The pipeline matches the
sentence-transformers one (tokenize, max 256 tokens → mean pooling → L2
normalize), so vectors are interchangeable. The query path (Phase 6) must use
this same module.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
MAX_TOKENS = 256
BATCH_SIZE = 32


def _model_file(filename: str) -> str:
    """Local huggingface_hub cache first; download only on the first run."""
    try:
        return hf_hub_download(MODEL_ID, filename, local_files_only=True)
    except Exception:  # noqa: BLE001 — not cached yet
        return hf_hub_download(MODEL_ID, filename)


@lru_cache(maxsize=1)
def _model() -> tuple[Tokenizer, ort.InferenceSession]:
    """Load once per process and reuse for every batch."""
    tokenizer = Tokenizer.from_file(_model_file("tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    tokenizer.enable_padding()
    session = ort.InferenceSession(
        _model_file("onnx/model.onnx"),
        providers=["CPUExecutionProvider"],
    )
    return tokenizer, session


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return an (n, 384) float32 array of unit-length embeddings."""
    tokenizer, session = _model()
    input_names = {i.name for i in session.get_inputs()}
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for start in range(0, len(texts), BATCH_SIZE):
        encodings = tokenizer.encode_batch(texts[start : start + BATCH_SIZE])
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        token_vecs = session.run(None, feeds)[0]  # (batch, seq, 384)
        weights = mask[..., None].astype(np.float32)
        pooled = (token_vecs * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        out[start : start + len(encodings)] = pooled
    return out
