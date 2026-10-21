"""The one place the core learns which Agent kits exist.

A kit is the specialised part of one kind of Agent (its tools, data, prompt and routes). Its manifest is plain
data for the capability catalog; the implementation module is imported only when services are built.
"""
import importlib
from functools import cache

from app.kits.job_search.manifest import MANIFEST as JOB_SEARCH

MANIFESTS = (JOB_SEARCH,)


@cache
def kits():
    """Implementation modules, each exposing ID, SCHEMA, DEFINITIONS, build, prompt, state, migrate and router."""
    return tuple(importlib.import_module(manifest['module']) for manifest in MANIFESTS)


def enabled(agent):
    return [kit for kit in kits() if kit.ID in agent.platform_capabilities]
