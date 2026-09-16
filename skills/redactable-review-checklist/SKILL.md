---
name: redactable-review-checklist
description: "Apply when reviewing PRs or Rust code that handles user data, secrets, or telemetry. Finds redactable mistakes: missing policies, unsafe escape hatches, and raw logging bypasses."
metadata:
  skillcatalog/display_name: "Redactable Review Checklist"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-09-16T00:00:00Z"
---
# Redactable Review Checklist

Targets `redactable` 0.13. Use when reviewing Rust code that handles user data, secrets, financial data, logs, traces, errors, or telemetry.

Lead with leak risk. A redaction bug is a security and privacy bug.

**Where to spend review effort.** Since 0.12 the compiler forces a declaration on every structural field and every referenced template field, so "someone forgot to think about this field" is now a compile error rather than a silent leak. What the compiler cannot check is whether the declaration is *correct*. Concentrate on the declarations that assert safety — `#[not_sensitive]`, the `Bypass*` wrappers, `.expose()` — and on the output paths that route around redaction entirely.

## Type-Level Checks

- Verify sensitive structured types derive `Sensitive` (or `SensitiveDual`).
- Verify sensitive text/error types derive `SensitiveDisplay` (or `SensitiveDual`).
- Verify a type needing both paths uses `SensitiveDual`, not two derives. Two derives produce conflicting `ToRedacted`, `Debug`, and slog impls; `#[sensitive(dual)]` is rejected with a migration diagnostic.
- Confirm `NotSensitive` and `NotSensitiveDisplay` appear only on types where **every** field is safe. These derives do not inspect fields; they record a claim.
- Confirm enum annotations sit on variant **fields**. Variant-level `#[sensitive(...)]` and `#[not_sensitive]` are compile errors.
- Confirm no handwritten `ToRedacted` sits beside a derive.

Red flag: `NotSensitive` or `NotSensitiveDisplay` on a type holding names, emails, addresses, tokens, raw payloads, customer data, account data, financial data, or user input. `NotSensitive` logs the type's **raw** JSON.

Red flag, and the most easily missed in review: **`NotSensitive` on a type with a field whose type derives `Sensitive`.** It compiles, and it logs that field raw — `NotSensitive` serializes the borrowed original, so the nested `#[sensitive(...)]` annotations never run. The nested type visibly carries annotations, so scanning for them shows protection that is not applied. Check the derive on the *containing* type, not just the annotations on the fields.

Red flag: assuming `SensitiveDisplay` provides ordinary `Display` or `Error`, or satisfies structural `Redactable`. It provides neither.

### Template: correct struct derives

```rust
// WRONG — no redaction at all; Debug and Serialize expose everything
#[derive(Debug, serde::Serialize)]
struct UserProfile {
    email: String,
    display_name: String,
    account_id: u64,
}

let profile = UserProfile {
    email: "alice@example.com".into(),
    display_name: "Alice".into(),
    account_id: 42,
};
assert!(format!("{profile:?}").contains("alice@example.com")); // raw, in any log line
```

```rust
// CORRECT — every field declared
use redactable::ToRedacted;

#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct UserProfile {
    #[sensitive(redactable::Email)]
    email: String,
    #[sensitive(redactable::Pii)]
    display_name: String,
    #[not_sensitive]
    account_id: u64,
}

let profile = UserProfile {
    email: "alice@example.com".into(),
    display_name: "Alice".into(),
    account_id: 42,
};
assert_eq!(
    profile.to_redacted().json(),
    serde_json::json!({
        "email": "al***@example.com",
        "display_name": "***ce",
        "account_id": 42,
    }),
);
```

## Field-Level Checks

- Verify sensitive `String` and `Cow<str>` fields carry `#[sensitive(Policy)]`, not `#[not_sensitive]`.
- Verify the chosen policy reveals no more than the logs need. Prefer `Secret` unless a visible suffix or email domain has a stated diagnostic purpose.
- Confirm nested declared types are **unannotated** so traversal walks them.
- Confirm containers are handled: an annotation recurses to contents; an unannotated container requires its contents to be declared.
- Confirm typed IP fields are bare when annotated `#[sensitive(IpAddress)]`; inside a container they need `SensitiveValue<_, IpAddress>`.
- Confirm no sensitive data sits in `HashMap` or `BTreeMap` **keys** — keys are never redacted.
- Confirm sets are not used where redaction could collapse distinct values and break count-sensitive behavior.
- Confirm custom `RedactionPolicy` implementations declare `type Kind`.

Red flag: `#[not_sensitive]` on a field named `name`, `email`, `phone`, `address`, `token`, `secret`, `password`, `key`, `payload`, `metadata`, `context`, `message`, or `reason`.

Red flag: an unannotated `serde_json::Value` in a type whose generated `Debug` reaches a sink. `.redact()` collapses it to `"[REDACTED]"`, but generated `Debug` prints its **raw** contents; annotate it `#[sensitive(Secret)]` when `Debug` must hide it too.

## Escape Hatch Checks

You MUST answer each question for every escape hatch. Flag it if any answer is unclear.

- Why is `#[not_sensitive]` correct for the data this field actually holds?
- Is the complete output of this `BypassDisplayRedaction` / `BypassDebugRedaction` / `BypassJsonRedaction` public?
- Does this `BypassTextRedaction` summary say what the author thinks it says? The wrapper validates nothing and allows empty text.
- Does `BypassRedaction<T>` wrap a value that contains sensitive fields? It is a passthrough and does not walk them.
- Is `.expose()`, `.expose_mut()`, or `.into_inner()` on a path that also formats, logs, errors with, or diagnostically serializes the value? `.into_inner()` discards the wrapper, so the policy stops travelling with the value.
- Was this declaration added to silence a compile error rather than to record a decision?

**Must-do:** Because every field now needs a declaration, `#[not_sensitive]` is common on ordinary operational fields. Do not let that volume dull review. On a `u64 id` it is routine; on a `String`, a nested struct, or anything foreign it is a finding until justified.

## Logging And Telemetry Checks

Search for raw output bypasses:

```text
println!
eprintln!
dbg!
tracing::info!
tracing::error!
log::info!
format!(
to_string()
serde_json::to_string
redact(          # the free function, not the method
```

These are not always wrong, but each needs proof that no sensitive value reaches them.

Two traps that compile cleanly and still leak:

- **Error `Display`.** When a type derives `SensitiveDisplay` and `thiserror::Error`, they read the same template but `Display` renders the **raw** values. Any `{err}`, `err.to_string()`, `log::error!("{e}")`, or `anyhow`/`eyre` chain is a raw output path. Require `.redacted_display()` or `.to_redacted()`.
- **Direct slog values.** Passing a borrowed `Sensitive` or `SensitiveDual` value straight to slog emits the fixed placeholder `"[REDACTED]"`, not its redacted fields. That is safe but usually not what the author intended. Require `.slog_redacted_json()` when the redacted object is wanted.
- **`redact(x)` instead of `x.redact()`.** The free function is bounded on the internal mapper trait, not on `Redactable`, so it accepts raw leaves and returns them unchanged — no declaration required, no error raised. It differs from the safe method by one character.

For tracing fields, suggest `.tracing_redacted_debug()` for the redacted Rust shape or `.tracing_redacted()` for text. Both work on structural `Sensitive` types; raw `String` satisfies neither.

At a custom `ToRedacted` sink, raw values do not compile. Callers must pass a derived type, a `SensitiveValue`, or an explicit `Bypass*` wrapper — and `BypassRedaction<T>` is deliberately not accepted.

## Serialization Checks

Serialization is not redaction.

- Serializing a `Sensitive` value without redacting first emits raw fields.
- `SensitiveValue<T, P>`, `BypassRedaction<T>`, `BypassDisplayRedaction<T>`, and `BypassDebugRedaction<T>` all serialize their **raw** inner value.
- `NotSensitive`'s `ToRedacted` emits raw JSON by design.

<!-- harness-setup
use redactable::ToRedacted;
let user_profile = User { id: 42, email: "alice@example.com".into() };
-->
```rust
// WRONG — serde emits the real values; nothing here redacts
let json = serde_json::to_string(&user_profile).unwrap();
assert!(json.contains("alice@example.com"));
tracing::info!(payload = %json, "processed request");

// CORRECT — take the redacted value from the boundary API
let safe = user_profile.to_redacted().text();
assert!(!safe.contains("alice@example.com"));
tracing::info!(payload = %safe, "processed request");
```

## Error Message Checks

- Verify `SensitiveDisplay` or `SensitiveDual` is used when any variant may carry sensitive data.
- Verify every template-referenced sensitive field is annotated. Unreferenced fields need no declaration under `SensitiveDisplay` — but `SensitiveDual` checks them all.
- **On any diff that adds a field to a `SensitiveDisplay` type, stop.** This is the single place where 0.12's "every field needs a declaration" rule does not apply: an unreferenced field compiles silently, however sensitive it is. Ask whether the type should now derive `SensitiveDual`.
- Verify error logging goes through `.redacted_display()` or `.to_redacted()`, never ordinary `Display`.
- Confirm source errors are not blindly displayed when their messages may contain user data.
- Confirm `{field:?}` on a `#[not_sensitive]` field is intended: it uses ordinary `Debug`, adding quotes and escaping.

### Template: correct error enum

```rust
// WRONG — email leaks through every output path
#[derive(Debug, thiserror::Error)]
enum AccountError {
    #[error("failed for {email}")]
    LookupFailed { email: String },
}

let err = AccountError::LookupFailed { email: "alice@example.com".into() };
assert_eq!(err.to_string(), "failed for alice@example.com");
```

```rust
// CORRECT — SensitiveDisplay redacts .redacted_display(); thiserror still supplies Error
use redactable::RedactableWithFormatter;

#[derive(thiserror::Error, redactable::SensitiveDisplay)]
enum AccountError {
    #[error("failed for {email}")]
    LookupFailed {
        #[sensitive(redactable::Email)]
        email: String,
    },
}

let err = AccountError::LookupFailed { email: "alice@example.com".into() };
assert_eq!(err.redacted_display().to_string(), "failed for al***@example.com");
assert_eq!(err.to_string(), "failed for alice@example.com"); // ← thiserror Display, still raw
// Still a finding if any call site formats this with {} instead of .redacted_display().
```

## Tests To Expect

- `.redact()` changes sensitive fields and preserves declared-public fields
- `.to_redacted().json()` matches an independently written expected object
- `.redacted_display()` redacts template fields
- nested types are walked without outer annotations
- `serde_json::Value` payloads redact to `[REDACTED]`
- logging helpers reject raw values, where compile-fail tests are available
- short values are fully masked, since keep-based policies fail closed

```rust
use redactable::Redactable;

#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct UserProfile {
    #[sensitive(redactable::Email)]
    email: String,
    #[sensitive(redactable::Pii)]
    display_name: String,
    #[not_sensitive]
    account_id: u64,
}

#[test]
fn redact_replaces_sensitive_fields() {
    let profile = UserProfile {
        email: "alice@example.com".into(),
        display_name: "Alice".into(),
        account_id: 42,
    };
    let redacted = profile.redact();
    // Assert the policy-shaped output, not a generic placeholder.
    assert_eq!(redacted.email, "al***@example.com");  // Email: first 2 local chars + domain
    assert_eq!(redacted.display_name, "***ce");       // Pii: last 2
    assert_eq!(redacted.account_id, 42);              // declared public, preserved
}
```

Pair `testing::assert_json_shape` with an independently written expected value; a matching shape does not prove correct masking.

**Must-do:** Do not ask for a test asserting that raw values appear in generated `Debug`. Generated `Debug` is redacted in every build mode, including your crate's `cfg(test)` and redactable's `testing` feature. A test written against pre-0.12 behavior will fail.

**[guarantee]** Generated `Debug` has two shapes. `Sensitive` prints a flat `"[REDACTED]"` per annotated field, so it hides policy output. `SensitiveDisplay` and `SensitiveDual` print the redacted template, which *carries* policy output and renders `#[not_sensitive]` fields raw — `{:?}` on an error type is not the safe default it looks like. Assert policy-shaped output through `.redact()` or `.to_redacted()`, not `Debug`.

## Migration Red Flags

**The defect to look for in an upgrade PR is a migration that cleared "no declared redaction behavior" errors by adding `#[not_sensitive]` in bulk.** That converts a compile error into a silent leak, and it is the one migration failure the compiler cannot catch. Read every `#[not_sensitive]` the diff adds against the data its field holds.

Renamed and removed APIs (`ToRedactedOutput`, `.redacted_output()`, `NotSensitiveDebug`, `slog_redacted_display()`, and the rest) all fail to compile by name, so they need no checklist. Two migration changes are semantic rather than mechanical and do deserve a look: `#[sensitive(dual)]` collapsing into `SensitiveDual`, and a custom `RedactionPolicy` gaining `type Kind`. Stale references can also survive in comments, doc text, and test names, where nothing compiles them.

## Review Finding Template

```
**Finding:** <what is wrong>
**Leak path:** <how sensitive data reaches output>
**Required declaration:** <derive, annotation, or adapter needed>
**Expected test:** <assertion that would catch regression>
```

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-field-policies
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-logging-boundaries
