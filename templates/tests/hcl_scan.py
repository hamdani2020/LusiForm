"""A small text scanner for resource blocks in the template modules. TEST ONLY.

It finds `resource "type" "name" { ... }` blocks and the top-level `count` expression of
each. It does not parse HCL; it relies on `terraform fmt` having normalised the files
(two-space indentation, closing brace in column zero). A block it cannot close is an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

RESOURCE_START = re.compile(r'^resource\s+"(aws_[a-z0-9_]+)"\s+"([a-z0-9_]+)"\s*\{\s*$')
COUNT = re.compile(r"^  count\s*=\s*(.+?)\s*$")


@dataclass(frozen=True)
class Block:
    module: str
    type: str
    name: str
    count: str | None

    @property
    def address(self) -> str:
        return f"{self.type}.{self.name}"


def resource_blocks(modules_dir: Path) -> list[Block]:
    blocks: list[Block] = []
    for module in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
        for tf_file in sorted(module.glob("*.tf")):
            lines = tf_file.read_text().splitlines()
            index = 0
            while index < len(lines):
                match = RESOURCE_START.match(lines[index])
                if not match:
                    index += 1
                    continue
                end = index + 1
                while end < len(lines) and lines[end] != "}":
                    end += 1
                if end >= len(lines):
                    raise ValueError(f"{tf_file}: unterminated block at line {index + 1}")
                count: str | None = None
                for line in lines[index + 1 : end]:
                    found = COUNT.match(line)
                    if found:
                        count = found.group(1)
                        break
                blocks.append(Block(module.name, match.group(1), match.group(2), count))
                index = end + 1
    return blocks
