"""Cross-encoder reranking with ONNX Runtime (no torch), for scripts/evaluate_reranker.py.

A cross-encoder reads the question and one candidate together and returns a relevance
score, so it can reorder the hybrid search's candidates. The model repos publish ONNX
exports; this runs them with onnxruntime + tokenizers.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

BATCH_SIZE = 16


class OnnxCrossEncoder:
    def __init__(self, session, tokenizer):
        self.session = session
        self.tokenizer = tokenizer
        self.input_names = {item.name for item in session.get_inputs()}

    @classmethod
    def from_hub(cls, repo_id: str, onnx_file: str, *, max_length: int = 512, threads: int = 2) -> OnnxCrossEncoder:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(hf_hub_download(repo_id, onnx_file), options, providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(hf_hub_download(repo_id, "tokenizer.json"))
        # Trim the longer side first: some guardians' questions alone exceed 512 tokens.
        tokenizer.enable_truncation(max_length=max_length, strategy="longest_first")
        tokenizer.enable_padding()
        return cls(session, tokenizer)

    def _score(self, query: str, passages: Sequence[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch([(query, passage) for passage in passages])
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64)}
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        logits = self.session.run(None, feeds)[0]
        return logits.reshape(len(passages), -1)[:, 0]

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scores = [self._score(query, passages[i : i + BATCH_SIZE]) for i in range(0, len(passages), BATCH_SIZE)]
        return np.concatenate(scores).tolist() if scores else []
