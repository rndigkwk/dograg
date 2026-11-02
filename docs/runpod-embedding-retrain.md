# RunPod에서 건강 임베딩 다시 학습하기

`scripts/train_embedding_gpu.py`를 빌린 GPU(RTX PRO 4000, 24GB)에서 돌리는 순서다. 왜 다시 학습하는지는 [위키](wiki/embedding-finetune.md) "과적합 점검"의 마지막 줄에 있다.

## 1. pod 준비

- 템플릿: PyTorch가 들어 있는 공식 RunPod 템플릿이면 된다. 공개 템플릿으로 저장하지 않는다(학습 데이터는 AI Hub 원문이라 공유 금지).
- 디스크: 볼륨 20GB면 충분하다. 체크포인트 9개를 모델 저장소에 올린 뒤에는 지운다.

## 2. pod 터미널에서 (bash)

```bash
cd /workspace && git clone --depth 1 --branch feat/embedding-retrain-gpu https://github.com/rndigkwk/dograg.git && cd dograg
```

```bash
pip install -q --ignore-installed blinker cryptography && pip install -q "sentence-transformers[train]>=5.1" mlflow python-dotenv huggingface_hub
```

토큰은 화면과 셸 기록에 남지 않게 `read -s`로 넣는다. Hugging Face 토큰은 비공개 데이터셋 읽기와 모델 저장소 쓰기 권한, DagsHub 토큰은 MLflow 기록용이다.

```bash
read -s -p "HF token: " HF_TOKEN && export HF_TOKEN && echo
```

```bash
read -s -p "DagsHub token: " MLFLOW_TRACKING_PASSWORD && export MLFLOW_TRACKING_PASSWORD && echo
```

먼저 몇 단계만 돌려 코드와 GPU를 확인한다(1분 안쪽, 업로드 없음).

```bash
python scripts/train_embedding_gpu.py --smoke --no-upload --local-mlflow --seeds 13 --epochs 2
```

본 학습: 시드 3개 × 3 epoch, 체크포인트 9개를 `<사용자>/ko-sroberta-dograg-b2`(비공개)에 올리고 DagsHub MLflow `health-embedding`에 기록한다.

```bash
python scripts/train_embedding_gpu.py 2>&1 | tee /workspace/retrain.log
```

## 3. 끝나면

- 마지막에 출력되는 JSON(시드·epoch별 dev 점수, `best_by_dev`)을 보내 준다.
- pod을 멈추고 볼륨을 지운다. 학습 데이터(`data/df.csv`, `data/finetune/queries.jsonl`)가 볼륨에 남기 때문이다.
- 로컬 평가(220문항 `useful@3`, 새 후보는 판사가 채점):

```bash
uv run --group tools python scripts/evaluate_finetuned_embedding.py --variants b --retrain
```
