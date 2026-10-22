"""Pinned local tokenizer. Never downloads resources or sends text to a service."""
from functools import lru_cache
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re


RESOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / 'resources/tokenizers/deepseek-v4'


@lru_cache(maxsize=1)
def load_tokenizer():
    from tokenizers import Tokenizer

    manifest = json.loads((RESOURCE_DIRECTORY / 'manifest.json').read_text())
    data = (RESOURCE_DIRECTORY / 'tokenizer.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest['sha256']:
        raise ValueError('Tokenizer checksum mismatch')
    return Tokenizer.from_str(data.decode('utf-8')), manifest


class TokenCounter:
    def __init__(self, model):
        self.tokenizer = None
        self.metadata = {'target_model': model, 'status': 'model_not_supported'}
        if not model or not re.fullmatch(r'deepseek-v4-(?:pro|flash)(?:\[1m\])?', model):
            return
        try:
            self.tokenizer, manifest = load_tokenizer()
            self.metadata.update(
                status='ready', id=manifest['id'], revision=manifest['revision'],
                sha256=manifest['sha256'], library='tokenizers',
                library_version=importlib.metadata.version('tokenizers'),
                add_special_tokens=False,
            )
        except Exception:
            # Missing resources or dependencies must not interrupt an answer.
            self.metadata['status'] = 'unavailable'

    def count(self, text):
        if self.tokenizer is None:
            return None
        try:
            return len(self.tokenizer.encode(text, add_special_tokens=False).ids)
        except Exception:
            self.metadata['status'] = 'encoding_failed'
            return None
