"""Export the fine-tuned health embedding model to ONNX (int8) for the app, and check it.

    uv run --group tools --with onnx python scripts/export_finetuned_onnx.py            # export + parity check
    uv run --group tools --with onnx python scripts/export_finetuned_onnx.py --upload   # also push onnx/

The app embeds questions with onnxruntime, not PyTorch (src/onnx_embeddings.py), from an ONNX file
with inputs input_ids / attention_mask and output last_hidden_state, like the base model's
`onnx/model_qint8_avx512_vnni.onnx`. This exports blanden77/ko-sroberta-dograg-b the same way,
quantizes the MatMul weights to int8 per channel (dynamic quantization), and compares the app's ONNX pipeline with
sentence-transformers (PyTorch) on real questions: cosine per question and the top-12 overlap
over the 19,206 corpus vectors. Files: output/onnx_b/onnx/model_qint8.onnx.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

REPO_ID = "blanden77/ko-sroberta-dograg-b"
OUT = PROJECT_DIR / "output" / "onnx_b"
ONNX_FILE = "onnx/model_qint8.onnx"


def export(model_dir: Path) -> Path:
    import torch
    from transformers import AutoModel

    model = AutoModel.from_pretrained(model_dir).eval()
    (OUT / "onnx").mkdir(parents=True, exist_ok=True)
    float_path = OUT / "onnx" / "model.onnx"
    sample = {"input_ids": torch.ones(2, 16, dtype=torch.long), "attention_mask": torch.ones(2, 16, dtype=torch.long)}

    class Wrapper(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, input_ids, attention_mask):
            return self.inner(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state

    torch.onnx.export(
        Wrapper(model), (sample["input_ids"], sample["attention_mask"]), str(float_path),
        input_names=["input_ids", "attention_mask"], output_names=["last_hidden_state"],
        dynamic_axes={"input_ids": {0: "batch_size", 1: "sequence_length"},
                      "attention_mask": {0: "batch_size", 1: "sequence_length"},
                      "last_hidden_state": {0: "batch_size", 1: "sequence_length"}},
        opset_version=17, dynamo=False,
    )
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantized = OUT / ONNX_FILE
    # MatMul weights only, one scale per output channel. The default (every op, one scale per
    # tensor) also quantized the embedding table: mean cosine to PyTorch 0.960 (min 0.937), against
    # 0.990 (0.985) here and 0.989 for the base model's official int8 file. Costs 75 MB of file size.
    quantize_dynamic(str(float_path), str(quantized), weight_type=QuantType.QInt8,
                     op_types_to_quantize=["MatMul"], per_channel=True)
    for name in ("tokenizer.json",):
        (OUT / name).write_bytes((model_dir / name).read_bytes())
    print(f"float {float_path.stat().st_size / 1e6:.0f} MB, int8 {quantized.stat().st_size / 1e6:.0f} MB")
    return quantized


def parity(model_dir: Path, quantized: Path) -> dict:
    import onnxruntime as ort
    from sentence_transformers import SentenceTransformer
    from tokenizers import Tokenizer

    from src.onnx_embeddings import OnnxSentenceEmbeddings

    onnx = OnnxSentenceEmbeddings(ort.InferenceSession(str(quantized), providers=["CPUExecutionProvider"]),
                                  Tokenizer.from_file(str(OUT / "tokenizer.json")))
    torch_model = SentenceTransformer(str(model_dir), device="cpu")
    torch_model.max_seq_length = 128
    short = [item["question"] for item in json.loads(
        (PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]]
    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        long = [row["qa.input"] for row in csv.DictReader(f)][:120]
    corpus = np.load(model_dir / "corpus_embeddings.npy")
    corpus /= np.linalg.norm(corpus, axis=1, keepdims=True)
    report = {}
    for name, questions in (("short", short), ("long", long)):
        a = np.array(onnx.embed_documents(questions))
        b = torch_model.encode(questions, convert_to_numpy=True, normalize_embeddings=True)
        cosine = (a * b).sum(axis=1)
        top_a = np.argsort(-(a @ corpus.T), axis=1)[:, :12]
        top_b = np.argsort(-(b @ corpus.T), axis=1)[:, :12]
        overlap = [len(set(x) & set(y)) / 12 for x, y in zip(top_a, top_b)]
        report[name] = {"questions": len(questions), "cosine_mean": round(float(cosine.mean()), 4),
                        "cosine_min": round(float(cosine.min()), 4), "top12_overlap_mean": round(float(np.mean(overlap)), 3)}
    print(json.dumps(report, indent=1))
    (OUT / "parity.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def upload(token: str) -> None:
    from huggingface_hub import HfApi

    HfApi(token=token).upload_file(path_or_fileobj=str(OUT / ONNX_FILE), path_in_repo=ONNX_FILE, repo_id=REPO_ID,
                                   commit_message="ONNX int8 export for the app (scripts/export_finetuned_onnx.py)")
    print("uploaded", f"{REPO_ID}/{ONNX_FILE}")


def main() -> int:
    from dotenv import load_dotenv
    from huggingface_hub import snapshot_download

    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env")
    token = os.environ["HF_TOKEN"]
    model_dir = Path(snapshot_download(REPO_ID, token=token))
    quantized = export(model_dir)
    parity(model_dir, quantized)
    if args.upload:
        upload(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
