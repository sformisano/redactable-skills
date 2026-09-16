# Validation record

How the current skill content was verified, and why each behavior-shaping change
was made. Recorded because these skills tell agents what is safe to log: a claim
here that is wrong in the leaking direction is a security defect, not a typo.

Crate under test: `redactable` 0.13.0 (crates.io release).
Mechanical gate: `harness/check_examples.py` — 45 blocks compiled, run, or
required to fail; 1 skipped with a recorded reason.

## Corrections

Each row is a claim that was wrong or unverified, the evidence that settled it,
and what the skills now say.

| Target | Class | Old claim | Evidence | Now |
| --- | --- | --- | --- | --- |
| `core-model` | behavior-shaping | "Treat redaction as opt-in. Assume fields remain visible unless annotated." | `require_declared_redaction` bound; every 0.10-era example failed to compile | Every field needs a declaration; an undeclared field is a compile error |
| `core-model`, `field-policies`, `review-checklist` | behavior-shaping | Generated `Debug` prints a flat `[REDACTED]` for every annotated field | Compiled probe: `SensitiveDisplay` Debug renders `card=************1234 user=alice` | Per-derive table; display derives carry policy output and raw `#[not_sensitive]` values |
| `core-model` | behavior-shaping | `[guarantee]` a `Drop` container cannot derive `Sensitive` | Compiled probe: Copy-field `Drop` struct compiles; `drop` ran twice | Unsupported, usually E0509, but Copy-field shapes compile and double-drop |
| `core-model`, `logging-boundaries`, `review-checklist` | behavior-shaping | `Debug` is unredacted in `cfg(test)` and under `testing` | `tests/integration_production_debug.rs`; no `cfg(test)` gating in the derive | Redacted in every build mode |
| `derive-selection`, `review-checklist` | behavior-shaping | *(absent)* | Compiled probe: `NotSensitive` over a `Sensitive` field logs `{"user":{"email":"alice@example.com"}}` | Documented as the most easily missed leak; nested annotations are inert |
| `core-model`, `review-checklist` | behavior-shaping | *(absent)* | Compiled probe: `redact("alice@example.com".to_owned())` returns it unchanged | Free `redact()` is a no-op on raw leaves and must not be used at a boundary |
| `derive-selection`, `review-checklist` | behavior-shaping | Template-omitted fields "need nothing" (stated neutrally) | `redacted_display/codegen.rs` collects bounds per placeholder only | Framed as the one gap in the declaration rule; adding a field is a review stop |
| `field-policies` | behavior-shaping | `#[sensitive(Policy)]` recurses through tuples, `Mutex`, `RwLock`, `Cell` | Compiled probes: all four rejected | Removed; traversal list and policy list are now distinguished |
| `logging-boundaries` | behavior-shaping | `SlogRedacted` usable as a safety gate | `slog.rs` impls for every `Bypass*` and `NotSensitive` type | Gate admits every declared escape hatch; proves a declaration exists, not that it is right |
| `core-model` | clarifying | Raw `Display` leak framed as thiserror-specific | No derive emits `Display`; any source of it is raw | Generalized to any `Display` impl |
| `field-policies` | clarifying | Scalars need a bare `Secret`; qualified primitives rejected | Compiled probe: `redactable::Secret` and `std::primitive::u32` both work | Removed; dispatch is type-directed |
| `derive-selection` | clarifying | `Clone`/`Serialize` required by "every derive" | `output.rs` bounds differ per derive | Scoped to `Sensitive` / `SensitiveDual` |
| `logging-boundaries` | clarifying | `SlogRedactedExt`'s "both methods exist on every producer" | `slog.rs:172` `where Self: Sized` | `.slog_redacted()` excluded on `&dyn ToRedacted` |
| `derive-selection` | clarifying | `Mutex`/`RwLock` render `<locked>` (unscoped) | Reachable only on declared unannotated fields | Scoped |

## Second review pass

An independent review after the first pass found further defects. Each was
reproduced before being accepted; one claim was checked and did not hold.

| Target | Class | Old claim | Evidence | Now |
| --- | --- | --- | --- | --- |
| `harness` | behavior-shaping | `compile_fail` proved only that a block failed | Fixture failing on a type mismatch passed the gate | Each block declares its expected diagnostic and is held to it |
| `harness`, `VALIDATION`, `README` | behavior-shaping | Weekly CI surfaces a new crate release | The check pins `=0.13.0`, so it passes indefinitely | Separate advisory `--check-latest` job compares the pin against crates.io |
| `logging-boundaries` | behavior-shaping | The slog gate admits every `Bypass*` wrapper | Compiled probe: `BypassTextRedaction` is not `SlogRedacted` | Names the three admitted wrappers and the two that are not |
| `field-policies` | behavior-shaping | `serde_json::Value` redacts "annotated or not" | Compiled probe: `#[not_sensitive]` keeps the payload raw | Scoped to unannotated fields, with the override called out |
| `field-policies` | behavior-shaping | Wrap in `SensitiveValue` for tuples, locks, and `Cell` | Compiled probes: fails for `Cell`, `Mutex`, `RwLock` | Per-shape table; locks need a separate log view |
| `logging-boundaries` | clarifying | "A test asserting raw values in `Debug` will fail" | Public and opaque fields print raw by design | Scoped to annotated fields |
| `wrappers`, `review-checklist` | clarifying | Raw-value review covered `.expose()` | `.expose_mut()` and `.into_inner()` also return raw | All three checked; `.into_inner()` drops the policy |
| `field-policies` | clarifying | Scalars accept `Secret` "and nothing else" | Compiled probe: a custom `SecretPolicyKind` policy works | Scoped to built-ins; the kind is what admits scalars |
| `derive-selection` | clarifying | Generic bound table omitted template fields | `DeclaredFormatting` is required on the complete type | Row added |
| `review-checklist` | clarifying | The free `redact()` "never fails" | Traversal and custom policies can panic | Reworded to what it actually does |
| `logging-boundaries` | clarifying | *(absent)* | `serialize_redacted_json` replaces the whole value on error | Documented, including that it does not catch panics |

Checked and not accepted: that the map guidance implied `BTreeMap<String, String>`
accepts an `IpAddress` annotation. The skill says the opposite — typed IPs are
bare-field-only, and maps are containers. The IP-map sealed key allowlist remains
deliberately omitted; its `on_unimplemented` message states the fix.

Also deliberately omitted: `#[redactable(legacy_formatting)]` and
`generated_formatting`. Both need a custom `PolicyApplicableRef` leaf or an
alias-hidden container, and their rejection messages name the required attribute.
`#[redactable(recursive)]` is covered, because its E0275 names no attribute.

## Gate check

No gate was softened. Every `must` / `never` / `Do not` present before this pass
is preserved, strengthened, or removed because the crate no longer behaves that
way. The removals, each replaced by a stricter or corrected rule:

- "Do not annotate standard leaves that are not sensitive" — inverted by 0.12;
  replaced by the stricter rule that every field needs a declaration.
- "Do not use qualified primitive paths" and "scalar `Secret` must be a bare
  identifier" — both false at 0.13, verified by compiling.
- "Matches on `RedactedOutput` must carry a wildcard arm" — the type is gone;
  `RedactedValue` is opaque and has no variants.
- "`Debug` shows raw values in tests, so do not log it" — false since 0.12; the
  replacement states the opposite and warns against tests asserting the old
  behavior.

Two gates dropped during rewriting were restored after this check: "every
sensitive leaf must carry a policy" and "values reaching a sink must go through
a named adapter."

## What is not verified

- The `tracing-valuable` example needs `RUSTFLAGS="--cfg tracing_unstable"`,
  which the harness does not set. Skipped with a recorded reason, as the crate
  does for its own equivalent example.
- Guidance on enabling `nested-values` in third-party slog drains is about
  crates outside this workspace.
- Judgment guidance — which policy to choose, when a `#[not_sensitive]` is
  justified — is not mechanically checkable and rests on review.

## Re-validating

```sh
python3 harness/selftest.py           # the checker can still fail
python3 harness/check_examples.py     # every example behaves as documented
```

CI runs both on every push and weekly.

The example check pins an exact version, so it cannot notice a new release by
itself — it keeps passing against the pinned crate. A separate advisory job runs
`--check-latest`, which compares the pin against the crates.io index and reports
when a newer release exists. That is the drift signal; the example run is the
correctness signal.

When a newer release appears, re-verify the affected claims against it before
touching `REDACTABLE_VERSION`. Never bump the pin to make a red build green.
