"""Explicit one-time public model download; runtime inference stays offline."""

import argparse
import json
from pathlib import Path
import sys

from huggingface_hub import snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from agent.voice.dictation_models import DEFAULT_MODEL, MODELS

parser = argparse.ArgumentParser()
parser.add_argument("--model-dir", required=True, type=Path)
parser.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL)
args = parser.parse_args()
repo_id = MODELS[args.model]["repo_id"]
revision = MODELS[args.model]["revision"]
snapshot_download(repo_id, revision=revision, local_dir=args.model_dir, token=False,
                  allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
(args.model_dir / "source.json").write_text(json.dumps({"repo_id": repo_id, "revision": revision}, indent=2), encoding="utf-8")
print(f"Downloaded {repo_id} at {revision}")
