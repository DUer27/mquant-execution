"""Tiny build backend so the project remains dependency-free."""
def build_wheel(*args, **kwargs):
    raise RuntimeError("Use the source checkout directly; no build dependencies are required")
def build_editable(*args, **kwargs):
    raise RuntimeError("Use the source checkout directly")
