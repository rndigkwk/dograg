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


QWEN_SYSTEM = ('Judge whether the Document meets the requirements based on the Query and the Instruct provided. '
               'Note that the answer can only be "yes" or "no".')
QWEN_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"


class OnnxQwenReranker:
    """Qwen3-Reranker (a causal LM): P("yes") at the last position of a fixed chat prompt
    (model card of onnx-community/Qwen3-Reranker-0.6B-ONNX). One candidate per forward pass,
    with an empty key/value cache; the graph returns logits for every position, so a long
    prompt costs sequence length x 151,669 floats of memory per call."""

    def __init__(self, session, tokenizer, *, instruction: str, max_tokens: int):
        self.session, self.tokenizer = session, tokenizer
        self.instruction, self.max_tokens = instruction, max_tokens
        self.yes = tokenizer.token_to_id("yes")
        self.no = tokenizer.token_to_id("no")
        self.past = [i for i in session.get_inputs() if i.name.startswith("past_key_values")]

    @classmethod
    def from_hub(cls, repo_id: str, onnx_file: str, *, threads: int = 2, instruction: str = QWEN_INSTRUCTION,
                 max_tokens: int = 1024) -> OnnxQwenReranker:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(hf_hub_download(repo_id, onnx_file), options, providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(hf_hub_download(repo_id, "tokenizer.json"))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return cls(session, tokenizer, instruction=instruction, max_tokens=max_tokens)

    def _ids(self, query: str, document: str) -> list[int]:
        head = f"<|im_start|>system\n{QWEN_SYSTEM}<|im_end|>\n<|im_start|>user\n<Instruct>: {self.instruction}\n\n<Query>: {query}\n\n<Document>: "
        tail = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n"
        head_ids = self.tokenizer.encode(head, add_special_tokens=False).ids
        tail_ids = self.tokenizer.encode(tail, add_special_tokens=False).ids
        doc_ids = self.tokenizer.encode(document, add_special_tokens=False).ids
        room = max(self.max_tokens - len(head_ids) - len(tail_ids), 64)
        return head_ids + doc_ids[:room] + tail_ids

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scores = []
        for passage in passages:
            ids = np.array([self._ids(query, passage)], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": np.ones_like(ids),
                     "position_ids": np.arange(ids.shape[1], dtype=np.int64)[None, :]}
            for item in self.past:
                feeds[item.name] = np.zeros((1, item.shape[1], 0, item.shape[3]), dtype=np.float32)
            last = self.session.run(["logits"], feeds)[0][0, -1]
            yes, no = float(last[self.yes]), float(last[self.no])
            top = max(yes, no)
            scores.append(np.exp(yes - top) / (np.exp(yes - top) + np.exp(no - top)))
        return scores
