"""
Shared set-up for tests/test_rag.py, loaded by pytest before the tests.

- Puts the repo root on the import path, so the tests can import rag_pipeline,
  rag_metrics and rag_judges whether run from the repo root or from tests/.
- Loads .env (OPENAI_API_KEY, DEEPEVAL_TELEMETRY_OPT_OUT) before DeepEval is
  imported, and opts out of telemetry if .env does not say so.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:          # CI passes the key as an environment variable instead
    pass
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
