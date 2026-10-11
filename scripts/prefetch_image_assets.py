"""Download the private data and the health embedding model into a container image at build time.

    docker build --secret id=hf_token,env=HF_TOKEN -t ragdog .   (runs this inside the build)

Cloud Run keeps files written at run time in memory, and a cold start that downloads ~340 MB
of data and the ONNX model is slow. The image carries both instead; the app then starts with
HF_HUB_OFFLINE=1. HF_TOKEN comes from a BuildKit secret, so it is not stored in any layer.
The image must stay in a private registry (the data may not be redistributed, src/private_data.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["data", "model"])
    args = parser.parse_args()
    from src import settings

    token = settings.get_setting("HF_TOKEN")
    if not token:
        print("HF_TOKEN is missing: build with --secret id=hf_token,env=HF_TOKEN", file=sys.stderr)
        return 1
    if args.what == "data":
        from src import private_data

        still = private_data.ensure()
        print("private data:", "ok" if not still else f"missing {still}")
        return 1 if still else 0
    from huggingface_hub import hf_hub_download

    from src import resources

    for filename in (resources.HEALTH_ONNX_FILE, "tokenizer.json"):
        path = hf_hub_download(resources.HEALTH_EMBEDDING_MODEL_NAME, filename, token=token)
        print("model file:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
