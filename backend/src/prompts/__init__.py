"""Prompt registry.

Prompt files are plain text and versioned by filename (`enrich_v1.txt`,
`compare_v1.txt`, ...). Old versions are never overwritten so every
analysis_runs row can be reproduced against the prompt it used (§10, §17).

This __init__.py exists only so the prompts directory ships as part of the
Python package; prompt text lives in `.txt` files loaded at runtime.
"""
