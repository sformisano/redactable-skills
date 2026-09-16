#!/usr/bin/env python3
"""Positive and negative controls for check_examples.py.

The example checker is a gate: a green run is taken as proof that every skill
example behaves as documented. A gate that cannot fail proves nothing, so this
runs the checker against fixtures with known-wrong blocks and asserts it
catches each one. The inverted case matters most: a ```rust,compile_fail block
that starts compiling must be reported, because that is how a crate change
silently turns an anti-pattern example into valid code.

Usage:
    python3 harness/selftest.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
CHECKER = HARNESS / "check_examples.py"

GOOD = '''---
name: fixture-good
---
# Fixture: blocks that must pass

## Compiles and runs

```rust
use redactable::{Secret, Sensitive, ToRedacted};

#[derive(Clone, serde::Serialize, Sensitive)]
struct Ok1 { #[sensitive(Secret)] s: String }

assert_eq!(Ok1 { s: "x".into() }.to_redacted().json()["s"], "[REDACTED]");
```

## Correctly marked compile_fail, with its expected diagnostic

<!-- harness-expect: has no declared redaction behavior -->
```rust,compile_fail
use redactable::Sensitive;

// Undeclared raw leaf: rejected since 0.12.
#[derive(Clone, serde::Serialize, Sensitive)]
struct Bad { name: String }
```

## Builds but is not run

```rust,no_run
fn main() { panic!("never executed under no_run"); }
```

## Explicitly skipped

```rust,ignore
this is not even rust
```

## Made whole by a setup directive

<!-- harness-setup
let user = User { email: "a@b.com".into() };
-->
```rust
use redactable::{Email, Sensitive, ToRedacted};

#[derive(Clone, serde::Serialize, Sensitive)]
struct User { #[sensitive(Email)] email: String }

assert_eq!(user.to_redacted().json()["email"], "*@b.com");
```
'''

CASES = {
    "does-not-compile": '''---
name: fixture-nocompile
---
# Fixture

## Block

```rust
use redactable::Sensitive;

#[derive(Clone, serde::Serialize, Sensitive)]
struct Bad { name: String }
```
''',
    "assertion-fails": '''---
name: fixture-assert
---
# Fixture

## Block

```rust
use redactable::{Secret, Sensitive, ToRedacted};

#[derive(Clone, serde::Serialize, Sensitive)]
struct Ok1 { #[sensitive(Secret)] s: String }

// The policy output is "[REDACTED]", so this assertion is wrong.
assert_eq!(Ok1 { s: "x".into() }.to_redacted().json()["s"], "x");
```
''',
    "test-fn-does-not-compile": '''---
name: fixture-testfn
---
# Fixture

## Block

```rust
#[test]
fn uses_a_type_that_does_not_exist() {
    let _ = NoSuchType { field: 1 };
}
```
''',
    "test-fn-assertion-fails": '''---
name: fixture-testassert
---
# Fixture

## Block

```rust
#[test]
fn assertion_is_wrong() {
    assert_eq!(1 + 1, 3);
}
```
''',
    "compile_fail-without-expectation": '''---
name: fixture-noexpect
---
# Fixture

## Block

```rust,compile_fail
use redactable::Sensitive;
#[derive(Clone, serde::Serialize, Sensitive)]
struct Bad { name: String }
```
''',
    "compile_fail-for-the-wrong-reason": '''---
name: fixture-wrongreason
---
# Fixture

## Block

<!-- harness-expect: has no declared redaction behavior -->
```rust,compile_fail
// Claims to show the undeclared-leaf rule; actually fails on a type mismatch.
let x: u32 = "not a number";
```
''',
    "compile_fail-that-compiles": '''---
name: fixture-inverted
---
# Fixture

## Block

<!-- harness-expect: some diagnostic that will never appear -->
```rust,compile_fail
// Perfectly valid: marking it compile_fail is the mistake.
fn main() { let _ = 1 + 1; }
```
''',
    "unknown-modifier": '''---
name: fixture-modifier
---
# Fixture

## Block

```rust,compile-fail
fn main() {}
```
''',
}


def run(skills_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--skills-dir", str(skills_dir)],
        capture_output=True,
        text=True,
    )


def fixture(root: Path, name: str, body: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(body)
    return directory


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        # Positive control: every supported mode, all behaving correctly.
        positive = root / "positive"
        positive.mkdir()
        fixture(positive, "fixture-good", GOOD)
        result = run(positive)
        if result.returncode != 0:
            failures.append(
                "POSITIVE CONTROL FAILED: valid fixtures were reported as broken.\n"
                f"{result.stdout}\n{result.stderr}"
            )
        elif "OK: 4 blocks behaved as declared" not in result.stdout:
            failures.append(
                "positive control passed but did not check the expected 4 blocks "
                "(run, compile_fail, no_run, setup) with 1 skipped:\n"
                f"{result.stdout}"
            )
        elif "skipped" not in result.stdout:
            failures.append(f"positive control did not report the ignored block:\n{result.stdout}")
        else:
            print("  positive control: all four modes pass, ignore is skipped")

        # Negative controls: each fixture must be caught.
        for name, body in CASES.items():
            negative = root / f"negative-{name}"
            negative.mkdir()
            fixture(negative, f"fixture-{name}", body)
            result = run(negative)
            if result.returncode == 0:
                failures.append(
                    f"NEGATIVE CONTROL FAILED: '{name}' was accepted but should have been caught.\n"
                    f"{result.stdout}"
                )
            else:
                print(f"  negative control: '{name}' correctly reported")

    print()
    if failures:
        print(f"SELFTEST FAILED ({len(failures)})\n")
        for failure in failures:
            print(f"{failure}\n")
        return 1
    print("SELFTEST OK: the checker fails when it should and passes when it should")
    return 0


if __name__ == "__main__":
    sys.exit(main())
