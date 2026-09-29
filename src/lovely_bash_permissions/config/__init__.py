"""Configuration loading, schema validation and effective-policy resolution.

This package is a boundary marker, nothing more: it deliberately re-exports
nothing.  Every module inside imports its siblings relatively
(``from .jsonc import read_jsonc_file``) and every consumer imports the leaf
module it actually needs
(``from lovely_bash_permissions.config.manager import PermissionsManager``).
Re-exporting here would mint a second import path for the same symbols, and
with it a second place for the modules to drift apart.
"""
