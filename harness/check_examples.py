#!/usr/bin/env python3
"""Compile and run every Rust example in the redactable skills.

The skills make claims about what the Rust compiler does. This turns those
claims into assertions: every ```rust block is compiled, every ```rust
block with a `main` or assertions is run, and every ```rust,compile_fail
block must actually fail to compile.

Usage:
    python3 harness/check_examples.py                 # check everything
    python3 harness/check_examples.py --skill core-model
    python3 harness/check_examples.py --keep          # keep the generated crate
    REDACTABLE_PATH=../redactable/redactable python3 harness/check_examples.py

Exit status is 0 only when every block behaved as its fence declares.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
HARNESS = REPO / "harness"
BUILD = HARNESS / ".build"

# The published version these skills describe. Bumping this is a deliberate,
# reviewed act: it is the moment the skills start describing a different crate.
REDACTABLE_VERSION = "0.13.0"

FENCE = re.compile(r"^(?P<indent>[ \t]*)```(?P<info>[^\n`]*)$")
SETUP = re.compile(r"<!--\s*harness-setup\s*(?P<body>.*?)-->", re.S)
SKIP = re.compile(r"<!--\s*harness-skip:\s*(?P<reason>.*?)-->", re.S)
HEADING = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")

# Fence modifiers we understand. Anything else on a rust fence is an error, so a
# typo like `compile-fail` cannot silently turn into "compile and run".
MODES = {"": "run", "no_run": "build", "compile_fail": "compile_fail", "ignore": "skip"}


@dataclass
class Block:
    skill: str
    path: Path
    line: int            # 1-based line of the opening fence
    heading: str
    mode: str
    code: str
    setup: str = ""
    skip_reason: str = ""
    ident: str = field(default="", init=False)

    @property
    def where(self) -> str:
        try:
            location = self.path.relative_to(REPO)
        except ValueError:
            location = self.path
        return f"{location}:{self.line} ({self.heading})"


def parse_info(info: str, where: str) -> tuple[str | None, str | None]:
    """Return (mode, error). mode is None when the block is not Rust."""
    parts = [p.strip() for p in info.strip().split(",") if p.strip()]
    if not parts or parts[0] != "rust":
        return None, None
    modifiers = parts[1:]
    if not modifiers:
        return "run", None
    if len(modifiers) > 1:
        return None, f"{where}: more than one fence modifier: {modifiers}"
    modifier = modifiers[0]
    if modifier not in MODES:
        known = ", ".join(sorted(k for k in MODES if k))
        return None, f"{where}: unknown fence modifier {modifier!r} (expected one of: {known})"
    return MODES[modifier], None


def parse_skill(path: Path) -> tuple[list[Block], list[str]]:
    skill = path.parent.name
    lines = path.read_text().splitlines()
    blocks: list[Block] = []
    errors: list[str] = []
    heading = "(top)"
    pending_setup = ""
    pending_skip = ""
    index = 0

    while index < len(lines):
        line = lines[index]

        matched_heading = HEADING.match(line)
        if matched_heading:
            heading = matched_heading.group("title")
            index += 1
            continue

        # Directives attach to the next fence, and only to the next one.
        if "harness-setup" in line or "harness-skip" in line:
            comment, consumed = read_comment(lines, index)
            setup_match = SETUP.search(comment)
            skip_match = SKIP.search(comment)
            if setup_match:
                pending_setup = setup_match.group("body").strip("\n")
            if skip_match:
                pending_skip = skip_match.group("reason").strip()
            index += consumed
            continue

        fence = FENCE.match(line)
        if not fence:
            index += 1
            continue

        where = f"{path.name}:{index + 1}"
        mode, error = parse_info(fence.group("info"), where)
        if error:
            errors.append(error)

        body, consumed = read_fence(lines, index, fence.group("indent"))
        if mode is not None:
            if pending_skip:
                mode = "skip"
            blocks.append(
                Block(
                    skill=skill,
                    path=path,
                    line=index + 1,
                    heading=heading,
                    mode=mode,
                    code=body,
                    setup=pending_setup,
                    skip_reason=pending_skip,
                )
            )
        elif pending_setup or pending_skip:
            errors.append(f"{where}: harness directive attached to a non-Rust block")
        pending_setup = ""
        pending_skip = ""
        index += consumed

    for ordinal, block in enumerate(blocks):
        block.ident = f"{skill.replace('-', '_')}__{ordinal:02d}"
    return blocks, errors


def read_comment(lines: list[str], start: int) -> tuple[str, int]:
    collected = []
    index = start
    while index < len(lines):
        collected.append(lines[index])
        if "-->" in lines[index]:
            break
        index += 1
    return "\n".join(collected), (index - start) + 1


def read_fence(lines: list[str], start: int, indent: str) -> tuple[str, int]:
    body: list[str] = []
    index = start + 1
    closing = f"{indent}```"
    while index < len(lines):
        if lines[index].rstrip() == closing.rstrip() and lines[index].strip() == "```":
            break
        body.append(lines[index][len(indent):] if lines[index].startswith(indent) else lines[index])
        index += 1
    return "\n".join(body), (index - start) + 1


def detach_tests(code: str) -> tuple[str, list[str]]:
    """Strip `#[test]` attributes and report the functions that carried them.

    `cargo build` removes `#[test]` functions before type-checking, so a test
    example would be silently unchecked: it could reference types that do not
    exist and still report success. Stripping the attribute makes the body
    compile like any other function, and the caller invokes it so its
    assertions actually run.
    """
    names: list[str] = []
    lines = code.splitlines()
    kept: list[str] = []
    pending_test = False

    for line in lines:
        if line.strip() == "#[test]":
            pending_test = True
            continue
        if pending_test:
            signature = re.match(r"\s*(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if signature:
                names.append(signature.group(1))
                pending_test = False
            elif line.strip().startswith("#["):
                kept.append(line)
                continue
            else:
                pending_test = False
        kept.append(line)

    return "\n".join(kept), names


def wrap(block: Block, prelude: str) -> str:
    """Build a standalone program from one block.

    Follows rustdoc's rule: a block that declares `fn main` is used as written,
    and anything else is wrapped. Items inside a function body are hoisted, so a
    setup line may reference a struct the block declares below it.
    """
    body, tests = detach_tests(block.code)
    has_main = re.search(r"^\s*(pub\s+)?(async\s+)?fn\s+main\s*\(", body, re.M) is not None
    setup = f"{block.setup}\n" if block.setup else ""
    if tests and not has_main:
        body += "\n" + "\n".join(f"{name}();" for name in tests)

    header = (
        "// GENERATED by harness/check_examples.py - do not edit.\n"
        f"// Source: {block.where}\n"
        "#![allow(unused, dead_code, unused_imports, clippy::all)]\n\n"
        "mod __prelude {\n"
        + "\n".join(f"    {line}" if line.strip() else "" for line in prelude.splitlines())
        + "\n}\nuse __prelude::*;\n\n"
    )
    if has_main:
        return f"{header}{setup}{body}\n"
    indented = "\n".join(f"    {line}" if line.strip() else "" for line in (setup + body).splitlines())
    return f"{header}fn main() {{\n{indented}\n}}\n"


def dependency_spec() -> tuple[str, str]:
    local = os.environ.get("REDACTABLE_PATH")
    if local:
        resolved = Path(local).expanduser().resolve()
        if not (resolved / "Cargo.toml").is_file():
            sys.exit(f"REDACTABLE_PATH={local} does not contain a Cargo.toml")
        return (
            f'redactable = {{ path = "{resolved}", features = {FEATURES} }}',
            f"local path {resolved}",
        )
    return (
        f'redactable = {{ version = "={REDACTABLE_VERSION}", features = {FEATURES} }}',
        f"crates.io ={REDACTABLE_VERSION}",
    )


FEATURES = '["slog", "tracing", "extras", "testing"]'

MANIFEST = """[package]
name = "{name}"
version = "0.0.0"
edition = "2024"
publish = false

{dependency}
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
slog = {{ version = "2.8", features = ["nested-values"] }}
tracing = "0.1"
thiserror = "2"
displaydoc = "0.2"
"""


def generate(blocks: list[Block], prelude: str) -> tuple[Path, Path]:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    dependency, _ = dependency_spec()

    for name in ("pass", "fail"):
        crate = BUILD / name
        (crate / "src" / "bin").mkdir(parents=True)
        (crate / "Cargo.toml").write_text(
            MANIFEST.format(name=f"examples_{name}", dependency="[dependencies]\n" + dependency)
        )
        (crate / "src" / "main.rs").write_text("fn main() {}\n")

    (BUILD / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["pass", "fail"]\nresolver = "2"\n'
    )

    for block in blocks:
        if block.mode == "skip":
            continue
        crate = "fail" if block.mode == "compile_fail" else "pass"
        target = BUILD / crate / "src" / "bin" / f"{block.ident}.rs"
        target.write_text(wrap(block, prelude))

    return BUILD / "pass", BUILD / "fail"


def cargo(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["cargo", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "CARGO_TERM_COLOR": "never"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill", help="check only skills whose directory name contains this")
    parser.add_argument("--keep", action="store_true", help="keep the generated crate for inspection")
    parser.add_argument("--list", action="store_true", help="list blocks and their modes, then exit")
    parser.add_argument("--skills-dir", type=Path, help="check this directory instead of skills/ (used by selftest)")
    options = parser.parse_args()

    prelude = (HARNESS / "prelude.rs").read_text()
    root = options.skills_dir.resolve() if options.skills_dir else SKILLS
    paths = sorted(root.glob("*/SKILL.md"))
    if options.skill:
        paths = [p for p in paths if options.skill in p.parent.name]
    if not paths:
        sys.exit("no SKILL.md files matched")

    blocks: list[Block] = []
    parse_errors: list[str] = []
    for path in paths:
        found, errors = parse_skill(path)
        blocks.extend(found)
        parse_errors.extend(errors)

    if parse_errors:
        print("Fence errors:\n")
        for error in parse_errors:
            print(f"  {error}")
        return 1

    if options.list:
        for block in blocks:
            note = f"  [{block.skip_reason}]" if block.skip_reason else ""
            print(f"{block.mode:<13} {block.ident:<34} {block.where}{note}")
        return 0

    checked = [b for b in blocks if b.mode != "skip"]
    skipped = [b for b in blocks if b.mode == "skip"]
    _, source = dependency_spec()
    print(f"redactable: {source}")
    print(f"{len(checked)} blocks to check, {len(skipped)} skipped\n")

    generate(blocks, prelude)
    failures: list[str] = []

    # One build covers every block expected to compile; cargo reports them all.
    pass_blocks = [b for b in checked if b.mode in ("run", "build")]
    broken: set[str] = set()
    if pass_blocks:
        print(f"building {len(pass_blocks)} blocks ...", flush=True)
        # --keep-going: without it cargo stops scheduling targets after the first
        # failures, so one broken block hides every block queued behind it.
        result = cargo(
            ["build", "--bins", "--keep-going", "--message-format=json"], BUILD / "pass"
        )
        attributed, unattributed = attribute(result.stdout, pass_blocks)
        for ident, rendered in attributed.items():
            broken.add(ident)
        failures.extend(
            f"{by_ident(pass_blocks)[ident].where}\n  did not compile:\n{indent_text(rendered)}"
            for ident, rendered in sorted(attributed.items())
        )
        if result.returncode != 0 and not attributed:
            detail = unattributed or result.stderr
            failures.append(f"build failed but no diagnostic could be attributed:\n{indent_text(detail)}")
        elif result.returncode != 0 and unattributed:
            failures.append(f"unattributed build errors:\n{indent_text(unattributed)}")

    # Run the blocks that carry assertions.
    run_blocks = [b for b in pass_blocks if b.mode == "run" and b.ident not in broken]
    if run_blocks and not broken:
        print(f"running {len(run_blocks)} blocks ...", flush=True)
        for block in run_blocks:
            binary = BUILD / "target" / "debug" / block.ident
            outcome = subprocess.run([binary], capture_output=True, text=True)
            if outcome.returncode != 0:
                detail = (outcome.stderr or outcome.stdout).strip()
                failures.append(f"{block.where}\n  example ran but failed:\n{indent_text(detail)}")

    # Each compile_fail block is built alone: one failure must not mask another.
    fail_blocks = [b for b in checked if b.mode == "compile_fail"]
    if fail_blocks:
        print(f"checking {len(fail_blocks)} compile_fail blocks ...", flush=True)
        for block in fail_blocks:
            result = cargo(["build", "--bin", block.ident], BUILD / "fail")
            if result.returncode == 0:
                failures.append(
                    f"{block.where}\n"
                    "  marked ```rust,compile_fail but it COMPILED.\n"
                    "  Either the crate changed and the skill is now wrong, or the\n"
                    "  example no longer demonstrates the mistake it describes."
                )

    if not options.keep:
        shutil.rmtree(BUILD, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} block(s)\n")
        for failure in failures:
            print(f"  {failure}\n")
        if options.keep:
            print(f"generated crate kept at {BUILD}")
        return 1

    print(f"OK: {len(checked)} blocks behaved as declared")
    for block in skipped:
        print(f"  skipped {block.where}: {block.skip_reason or 'marked ```rust,ignore'}")
    return 0


def indent_text(text: str, prefix: str = "    ") -> str:
    return "\n".join(f"{prefix}{line}" for line in text.strip().splitlines())


def by_ident(blocks: list[Block]) -> dict[str, Block]:
    return {b.ident: b for b in blocks}


def attribute(stdout: str, blocks: list[Block]) -> tuple[dict[str, str], str]:
    """Map cargo's diagnostics back to the skill block they came from.

    Reads `--message-format=json` rather than scraping rendered stderr. Text
    scraping silently dropped diagnostics it could not parse, which made the
    harness report success for blocks that had in fact failed to compile.
    """
    known = by_ident(blocks)
    per_block: dict[str, list[str]] = {}
    orphaned: list[str] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("reason") != "compiler-message":
            continue
        message = record.get("message") or {}
        if message.get("level") != "error":
            continue
        rendered = (message.get("rendered") or message.get("message") or "").rstrip()
        if not rendered:
            continue

        idents = {
            match.group(1)
            for span in message.get("spans") or []
            for match in [re.search(r"([A-Za-z0-9_]+)\.rs$", span.get("file_name", ""))]
            if match and match.group(1) in known
        }
        if idents:
            for ident in idents:
                per_block.setdefault(ident, []).append(rendered)
        else:
            orphaned.append(rendered)

    # Keep the first two diagnostics per block: the first is almost always the
    # real cause, and a wall of follow-on errors buries the file it came from.
    collapsed = {
        ident: "\n".join(messages[:2]) for ident, messages in per_block.items()
    }
    return collapsed, "\n".join(orphaned[:3])


if __name__ == "__main__":
    sys.exit(main())
