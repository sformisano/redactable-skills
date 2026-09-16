# Example harness

The redactable skills make claims about what the Rust compiler does. This
harness turns those claims into assertions, so a crate release that changes
behavior fails a build here instead of quietly leaving the skills wrong.

```sh
python3 harness/check_examples.py            # check every skill
python3 harness/check_examples.py --list     # show each block and its mode
python3 harness/check_examples.py --skill core-model
python3 harness/check_examples.py --keep     # keep the generated crate to inspect
python3 harness/selftest.py                  # prove the checker can still fail
```

## Which crate is checked

By default, the published release pinned in `check_examples.py`
(`REDACTABLE_VERSION`). That is deliberate: the skills describe the crate a
reader will actually depend on, not an unreleased working tree.

To check against local crate work before a release:

```sh
REDACTABLE_PATH=../redactable/redactable python3 harness/check_examples.py
```

**Bumping `REDACTABLE_VERSION` is a reviewed act.** It is the moment the skills
start describing a different crate, and every block has to be re-checked against
it. Do not bump it to make a red build go green.

## Writing a checkable example

The fence info string declares what the block claims. The harness holds it to
that claim.

| Fence | Meaning |
|---|---|
| ` ```rust ` | Compiles and runs. A failed `assert!` fails the build. |
| ` ```rust,no_run ` | Compiles. Not executed. |
| ` ```rust,compile_fail ` | Must **not** compile, **and** must fail for the documented reason. |
| ` ```rust,ignore ` | Not checked. Needs a reason; see below. |
| ` ```text `, ` ```toml `, … | Not Rust, not checked. |

Anything else on a `rust` fence is an error, so `compile-fail` cannot silently
become "compile and run".

**A `compile_fail` block must declare the diagnostic it expects.** Checking only
that compilation failed proves nothing: a block that fails on a typo passes just
as happily as one that demonstrates the rule. Name a distinctive fragment of the
real diagnostic, and the checker holds the block to it.

````markdown
<!-- harness-expect: PolicyField<Pii> -->
```rust,compile_fail
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct Account {
    #[sensitive(redactable::Pii)]
    user: User,
}
```
````

A `compile_fail` block without the directive is rejected outright.

**Put the expected output in an assertion, not a comment.** A comment reading
`// "al***@example.com"` cannot fail. `assert_eq!` can, and then the
documentation is the test.

```rust
let redacted = profile.redact();
assert_eq!(redacted.email, "al***@example.com");
```

**Pair anti-patterns as two fences, not one.** A single block holding both a
wrong and a right version defines the same type twice, so it cannot compile and
neither half gets checked. Split them: the wrong one `compile_fail`, the right
one plain.

**Wrapping follows rustdoc's rule.** A block declaring `fn main` is used as
written; anything else is wrapped in one. Items inside a function body are
hoisted, so setup may reference a type the block declares further down.

## Making a snippet whole

Examples are for readers first. When a snippet is clearer without ceremony, put
the ceremony in a directive instead of in the code block:

````markdown
<!-- harness-setup
let user = User { email: "a@b.com".into() };
-->
```rust
tracing::info!(user = user.tracing_redacted_debug(), "login attempt");
```
````

The directive attaches to the next fence only, and its lines are inserted at the
top of the generated `main`.

Common support types (`Settings`, `RetryConfig`, `ForeignConfig`,
`MerchantAccount`, `LogSink`, `CapturingSink`, `discard_logger()`) come from
`prelude.rs` and are glob-imported, so a block declaring its own `User` shadows
the prelude rather than colliding with it.

Keep `prelude.rs` small. It is not delivered with the skills: an agent copying
an example out of a skill does not get it, so anything load-bearing for
understanding belongs in the example itself.

## Skipping

`rust,ignore` and `<!-- harness-skip: reason -->` both remove a block from
checking, and every skip is printed on a green run so it stays visible. Use them
for genuine fragments — a lone struct field, a snippet whose surrounding code
would swamp the point — and record why. A skip is an unverified claim in a
document whose purpose is to be trusted.

## Release drift

```sh
python3 harness/check_examples.py --check-latest
```

The example check pins an exact version, so it keeps passing against that crate
after a newer one ships. This compares the pin against the crates.io index and
exits non-zero when it has fallen behind. CI runs it weekly as an advisory job.

It never edits the pin. Deciding that the skills now describe a different crate
is a review, not an automatic bump.

## Self-test

`selftest.py` runs the checker against fixtures that are known-good and
known-broken, and asserts each verdict. It covers the cases that matter most: a `compile_fail` block that starts
compiling, one that fails for the wrong reason, and one with no declared
expectation at all. Each is a way a documented anti-pattern quietly stops being
demonstrated. Run it after changing the checker.
