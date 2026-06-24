"""Transcript parser for Claude Code session JSONL files."""
from __future__ import annotations

import json
from pathlib import Path

from eval.models import Event, ParsedTranscript, TextOutputEvent, ToolCallEvent


class TranscriptParser:
    """Parses a Claude Code .jsonl transcript file into ParsedTranscript."""

    def parse(self, transcript_path: str | Path) -> ParsedTranscript:
        path = Path(transcript_path)
        if not path.exists():
            raise FileNotFoundError(f"Transcript file not found: {path}")

        events: list[Event] = []
        turn_boundaries: list[int] = [0]
        total_lines = 0
        parse_failures = 0

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    parse_failures += 1
                    continue

                entry_type = entry.get("type", "")

                if entry_type == "human":
                    if len(events) > 0:
                        turn_boundaries.append(len(events))

                elif entry_type == "assistant":
                    message = entry.get("message", {})
                    content_blocks = message.get("content", [])
                    for block in content_blocks:
                        block_type = block.get("type", "")
                        if block_type == "tool_use":
                            events.append(ToolCallEvent(
                                tool=block.get("name", ""),
                                input=block.get("input", {}),
                            ))
                        elif block_type == "text":
                            text = block.get("text", "")
                            if text.strip():
                                events.append(TextOutputEvent(text=text))

        if total_lines > 0 and parse_failures == total_lines:
            raise ValueError(
                f"Transcript completely unparseable: {path} ({total_lines} lines, all failed JSON decode)"
            )

        return ParsedTranscript(events=events, turn_boundaries=turn_boundaries)
