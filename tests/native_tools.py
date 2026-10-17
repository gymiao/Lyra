"""Explicit pinned native tools; defaults follow the checkout, never a machine path."""
import os
from pathlib import Path

def native_engine_root():
    return Path(os.environ.get('LYRAX_TEST_ENGINE_ROOT',str(Path(__file__).resolve().parents[1]/'.tools/lean')))

def native_dotnet():
    return Path(os.environ.get('LYRAX_TEST_DOTNET',str(Path(__file__).resolve().parents[1]/'.tools/dotnet/dotnet')))
