"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    cli

Purpose:
    Command-line entry point for the A01 agent.

Until this package existed the agent had no entry point at all: every
capability was reachable only by importing Python modules directly, which
meant A01 could not be started, queried, or operated as a program.

Usage
-----
    python -m cli investigate --subject subject.json
    python -m cli investigate --address 0xabc... --format json
    python -m cli detectors
    python -m cli doctor
"""

from __future__ import annotations

from .main import build_parser, main

__all__ = ["build_parser", "main"]
