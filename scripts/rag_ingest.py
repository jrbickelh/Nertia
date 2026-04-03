#!/usr/bin/env python3
"""Nightly RAG ingestion — cron job to keep knowledge base up to date."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.rag.ingest import run_full_ingest


if __name__ == "__main__":
    asyncio.run(run_full_ingest())
