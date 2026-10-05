"""ko-sroberta query embeddings with ONNX Runtime instead of PyTorch.

sentence-transformers needs torch, which costs several hundred MB of RAM on
Streamlit Community Cloud. The model repo publishes ONNX exports of the same
weights, so the app runs those with onnxruntime + tokenizers and reproduces the
sentence-transformers pipeline: tokenizer (max 128 tokens) -> transformer ->
mean pooling over the attention mask -> L2 normalization.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from langchain_core.embeddings import Embeddings

DEFAULT_REPO = "jhgan/ko-sroberta-multitask"
DEFAULT_ONNX_FILE = "onnx/model_qint8_avx512_vnni.onnx"
BATCH_SIZE = 32


def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    weights = mask[..., None].astype(hidden.dtype)
    summed = (hidden * weights).sum(axis=1)
    return summed / np.clip(weights.sum(axis=1), 1e-9, None)


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)


class OnnxSentenceEmbeddings(Embeddings):
    def __init__(self, session, tokenizer, *, normalize: bool = True):
        self.session = session
        self.tokenizer = tokenizer
        self.normalize = normalize
        self.input_names = {item.name for item in session.get_inputs()}

    @classmethod
    def from_hub(
        cls,
        repo_id: str = DEFAULT_REPO,
        onnx_file: str = DEFAULT_ONNX_FILE,
        *,
        threads: int = 2,
        normalize: bool = True,
    ) -> OnnxSentenceEmbeddings:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            hf_hub_download(repo_id, onnx_file), options, providers=["CPUExecutionProvider"]
        )
        # tokenizer.json already truncates to 128 tokens and pads to the batch's longest.
        tokenizer = Tokenizer.from_file(hf_hub_download(repo_id, "tokenizer.json"))
        return cls(session, tokenizer, normalize=normalize)

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(list(texts))
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feeds)[0]
        vectors = mean_pool(hidden, mask)
        return l2_normalize(vectors) if self.normalize else vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        rows = [self._embed(texts[i : i + BATCH_SIZE]) for i in range(0, len(texts), BATCH_SIZE)]
        return np.vstack(rows).tolist() if rows else []

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0].tolist()
