"""Build the care-guide chunks from the 동물사랑배움터 (농림수산식품교육문화정보원) education material.

    uv run python scripts/build_care_guides.py [--source DIR] [--dry-run]

Why: the AI Hub consultations are mostly about symptoms, so everyday care (grooming, walks, disasters,
old age) is thin or missing (docs/wiki/retrieval-experiments.md, basic care questions, 2026-10-10).
These guides are public education material for guardians; they carry no KOGL mark, so they are kept
private like the report PDFs (src/private_data.py) and an answer quotes a short piece with the
source and the page's link.

Two of the PDFs are designed slides and a leaflet with no text layer, and Tesseract misreads them;
their pages are read by the chat model from the page image, once, into data/care_guides/ocr.json
(one call per page, 14 pages). The others keep their own PDF text.

The search model (ko-sroberta, as the health search) reads 128 tokens, about 250 characters of this
text, so each page is cut into CHUNK_CHARS pieces with OVERLAP; the answer gets the piece's wider
CONTEXT_CHARS window. The pieces go to data/care_guides/chunks.json and their vectors to
vectors.npy (same order, L2-normalized); src/tools/care_guides.py searches them. No chat model calls
once ocr.json holds every image page.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
OUT_DIR = PROJECT_DIR / "data" / "care_guides"
BOARD = "https://apms.epis.or.kr/home/kor/board.do?menuPos=16&act=detail&idx={}"
ORGANIZATION = "농림수산식품교육문화정보원 동물사랑배움터"
CHUNK_CHARS = 240
OVERLAP = 60
CONTEXT_CHARS = 700  # the piece and what is around it on the page
MIN_PAGE_CHARS = 80  # covers, blank pages and closing pages

# file: (title, board post, how its text is read)
GUIDES = {
    "반려견_공공예절_교육.pdf": ("반려견 공공예절 교육 자료", 257, "vision"),
    "반려동물_재난대응_가이드라인.pdf": ("반려동물 가족을 위한 재난 대응 가이드라인", 639, "text"),
    "반려동물과의_이별_리플릿.pdf": ("반려동물과의 이별, 미리 알고 함께 준비합니다", 1542, "vision"),
    "행동지도_윤리_가이드라인.pdf": ("건강한 반려문화 조성을 위한 행동지도 윤리 가이드라인", 1454, "text"),
}
# Public-licence guides (공공누리 제1유형, source credited) kept in the repository as text, one page each:
# file in data/public_guides: (title, organization, original page). Lines starting with "#" or "- " are
# the file's own header (title, source, licence) and are not searched.
PUBLIC_DIR = PROJECT_DIR / "data" / "public_guides"
PUBLIC_GUIDES = {
    "mafra_summer_2026-06-16.md": ("함께여서 더 특별한 반려동물과의 여름나기", "농림축산식품부",
                                   "https://www.mafra.go.kr/bbs/home/792/578176/artclView.do"),
}

VISION_PROMPT = (
    "이 이미지는 반려동물 보호자 교육 자료의 한 쪽입니다. 쪽에 쓰인 글을 읽는 순서대로 그대로 옮겨 적으세요. "
    "제목, 본문, 표, 그림 속 글을 모두 포함하고, 그림만 있는 부분은 건너뜁니다. "
    "없는 글을 지어내거나 요약하지 말고, 읽을 수 없는 글자는 [?]로 적으세요. 옮긴 글만 답하세요."
)
# Misreadings found when checking the transcriptions against the page images, and boxes whose layout the
# transcription flattened: the leaflet's "where to report" boxes read "온라인 신고 국가동물보호 정보시스템 정부24
# 방문 신고 • 소유자의 주소지 …", and the answer to "반려견 사망 신고는 어디에 하나요?" said the material did not
# say where (production, 2026-10-19). Written out as the image shows them.
OCR_CORRECTIONS = {
    ("반려견_공공예절_교육.pdf", 10): [("위모관리", "외모관리")],
    ("반려동물과의_이별_리플릿.pdf", 2): [(
        "온라인 신고\n국가동물보호\n정보시스템\n정부24\n\n방문 신고\n• 소유자의 주소지\n관할 시·군·구청 방문",
        ("신고하는 곳: 온라인 신고는 국가동물보호정보시스템 또는 정부24에서 하고, "
         "방문 신고는 소유자의 주소지 관할 시·군·구청에 방문해서 합니다."),
    )],
}
_DOT_LEADER = re.compile(r"[·…]{3,}|\.{5,}")


def read_page_image(client, page, model: str) -> str:
    image = base64.b64encode(page.get_pixmap(dpi=150).tobytes("png")).decode()
    response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
    ]}])
    return response.choices[0].message.content.strip()


_SENTENCE_END = re.compile(r"(?<=[.!?。])\s|(?<=다\.)|(?<=요\.)")
END_REACH, START_REACH = 200, 100  # how far a window may grow to end or start at a sentence boundary


def sentence_window(text: str, lo: int, hi: int) -> str:
    """text[lo:hi], its end moved on to the end of the sentence it cuts (at most END_REACH further) and its
    start back to after a sentence end (at most START_REACH earlier, else as it was). A window cut mid-sentence
    left "신고하는 곳: 온" as the leaflet's last words, and the answer said the place was not given."""
    if hi < len(text):
        end = _SENTENCE_END.search(text, hi, min(len(text), hi + END_REACH))
        hi = end.end() if end else hi
    if lo > 0:
        before = [m.end() for m in _SENTENCE_END.finditer(text, max(0, lo - START_REACH), lo + 1)]
        lo = before[-1] if before else lo
    return text[lo:hi].strip()


def chunks_of(text: str) -> list[tuple[str, str]]:
    """(piece, its context) pairs over one page's text."""
    text = " ".join(text.split())
    pairs, start = [], 0
    while True:
        middle = start + CHUNK_CHARS // 2
        lo = max(0, min(middle - CONTEXT_CHARS // 2, len(text) - CONTEXT_CHARS))
        pairs.append((text[start:start + CHUNK_CHARS], sentence_window(text, lo, lo + CONTEXT_CHARS)))
        if start + CHUNK_CHARS >= len(text):
            return pairs
        start += CHUNK_CHARS - OVERLAP


def is_contents_page(text: str) -> bool:
    return len(_DOT_LEADER.findall(text)) >= 3


def embed(texts: list[str]) -> np.ndarray:
    from src.onnx_embeddings import OnnxSentenceEmbeddings
    from src.resources import HEALTH_EMBEDDING_MODEL_NAME, HEALTH_EMBEDDING_REVISION, HEALTH_ONNX_FILE

    model = OnnxSentenceEmbeddings.from_hub(HEALTH_EMBEDDING_MODEL_NAME, HEALTH_ONNX_FILE, revision=HEALTH_EMBEDDING_REVISION)
    vectors = np.asarray(model.embed_documents(texts), dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def main(argv: list[str] | None = None) -> int:
    import pymupdf

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=OUT_DIR, help="folder holding the PDFs")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="count pages and model calls only")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    ocr_path = args.out / "ocr.json"
    ocr = json.loads(ocr_path.read_text(encoding="utf-8")) if ocr_path.is_file() else {}
    to_read = [(name, number) for name, (_, _, mode) in GUIDES.items() if mode == "vision"
               for number in range(1, len(pymupdf.open(args.source / name)) + 1)
               if str(number) not in ocr.get(name, {})]
    print(f"pages to read from the image: {len(to_read)} (one model call each)")
    if args.dry_run:
        return 0
    if to_read:
        from dotenv import load_dotenv
        from openai import OpenAI

        from src.resources import CHAT_MODEL_NAME

        load_dotenv(PROJECT_DIR / ".env")
        client = OpenAI()
        for name, number in to_read:
            page = pymupdf.open(args.source / name)[number - 1]
            ocr.setdefault(name, {})[str(number)] = read_page_image(client, page, CHAT_MODEL_NAME)
            print(f"read {name} p.{number}")
            args.out.mkdir(parents=True, exist_ok=True)
            ocr_path.write_text(json.dumps(ocr, ensure_ascii=False, indent=1), encoding="utf-8")

    chunks = []
    for name, (title, post, mode) in GUIDES.items():
        doc = pymupdf.open(args.source / name)
        for number, page in enumerate(doc, start=1):
            text = ocr[name][str(number)] if mode == "vision" else page.get_text()
            for wrong, right in OCR_CORRECTIONS.get((name, number), []):
                text = text.replace(wrong, right)
            if len(text.strip()) < MIN_PAGE_CHARS or is_contents_page(text):
                continue
            for part, (piece, context) in enumerate(chunks_of(text)):
                chunks.append({"id": f"{Path(name).stem}-p{number}-{part}", "title": title, "page": number,
                               "organization": ORGANIZATION, "url": BOARD.format(post), "text": piece,
                               "context": context})
    for name, (title, organization, url) in PUBLIC_GUIDES.items():
        lines = (PUBLIC_DIR / name).read_text(encoding="utf-8").splitlines()
        text = "\n".join(line for line in lines if not line.startswith(("#", "- ")))
        for part, (piece, context) in enumerate(chunks_of(text)):
            chunks.append({"id": f"{Path(name).stem}-p1-{part}", "title": title, "page": 1,
                           "organization": organization, "url": url, "text": piece, "context": context})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(args.out / "vectors.npy", embed([chunk["text"] for chunk in chunks]))
    for title, *_ in [*GUIDES.values(), *PUBLIC_GUIDES.values()]:
        print(f"{title}: {sum(c['title'] == title for c in chunks)} chunks")
    print(f"{len(chunks)} chunks -> {args.out / 'chunks.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
