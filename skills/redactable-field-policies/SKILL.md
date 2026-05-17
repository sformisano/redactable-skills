---
name: redactable-field-policies
description: "Use when adding or reviewing redactable field annotations to choose safe policies for leaves, containers, scalars, JSON, maps, and sets."
metadata:
  skillcatalog/display_name: "Redactable Field Policies"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-05-17T11:10:10Z"
---
# Redactable Field Policies

Use this skill when adding or reviewing `#[sensitive(...)]` and `#[not_sensitive]` fields.

Follow the core rule: annotate sensitive leaves, not sensitive containers.

## Leaves Need Policies

Treat a leaf as any value the macro cannot walk into, such as `String`, `Cow<str>`, a scalar, or a foreign leaf wrapper. Add `#[sensitive(Policy)]` to every leaf that can contain user data, secrets, financial data, or raw user input.

```rust
#[derive(Clone, redactable::Sensitive)]
struct UserProfile {
    user_id: u64,
    #[sensitive(redactable::Pii)]
    full_name: String,
    #[sensitive(redactable::Email)]
    email: String,
}
```

Leave a `String` unannotated only when the value is intentionally non-sensitive after redaction.

## Containers Should Usually Be Unannotated

If a field's type derives `Sensitive`, leave the outer field unannotated so the nested type's own policies run.

```rust
#[derive(Clone, redactable::Sensitive)]
struct Customer {
    #[sensitive(redactable::Email)]
    email: String,
}

#[derive(Clone, redactable::Sensitive)]
struct Order {
    customer: Customer,
}
```

Do not write `#[sensitive(Pii)] customer: Customer`. That treats the whole field as one leaf and bypasses nested policies.

## Built-In Policies

| Policy | Use for | String output |
|---|---|---|
| `Secret` | passwords, keys, raw secrets | full redaction, usually `[REDACTED]` |
| `Token` | API keys, bearer tokens, session tokens | keeps last 4 characters |
| `Email` | email addresses | keeps first 2 local-part chars and the domain |
| `CreditCard` | card numbers or PANs | keeps last 4 characters |
| `Pii` | names, addresses, general personal data | keeps last 2 characters |
| `PhoneNumber` | phone numbers | keeps last 4 characters |
| `IpAddress` | IP strings | keeps last 4 characters |
| `BlockchainAddress` | wallet addresses | keeps last 6 characters |

Use `Secret` when partial visibility is not useful. Use a more specific policy only when the visible suffix or email domain has a clear diagnostic purpose.

## Scalars

Use only `#[sensitive(Secret)]` for scalar fields.

```rust
use redactable::{Secret, Sensitive};

#[derive(Clone, Sensitive)]
struct LoginAttempt {
    #[sensitive(Secret)]
    failed_count: u32,
    #[sensitive(Secret)]
    enabled: bool,
}
```

Import `Secret` and use the bare policy name for scalars. The derive recognizes scalar `Secret` as the bare identifier, so `#[sensitive(redactable::Secret)]` is rejected for scalar fields. This restriction applies only to scalars; string leaves and string containers can use imported or qualified policy paths.

Expect scalar redaction to yield these defaults:

- numbers become `0`
- floats become `0.0`
- booleans become `false`
- chars become `'*'`

Use bare primitive names like `u32`, `bool`, or `char`. Do not use qualified primitive paths such as `std::primitive::u32`; the derive macro does not recognize them as scalar types.

## Container Types

Apply `#[sensitive(Policy)]` to fields wrapped in these common container types when the contained leaves are sensitive:

- `Option<String>`
- `Vec<String>`
- `Box<String>`
- `Arc<String>` and `Rc<String>` when clone bounds are met
- `Result<T, E>`
- maps and sets
- nested combinations such as `Option<Vec<String>>`

```rust
#[derive(Clone, redactable::Sensitive)]
struct ContactList {
    #[sensitive(redactable::Email)]
    emails: Vec<String>,
    #[sensitive(redactable::Secret)]
    recovery_codes: Option<Vec<String>>,
}
```

Use owned `String` or `Cow<str>` for structural redaction. Do not use `&str`; it is not supported for `Sensitive` structural redaction.

## Maps And Sets

Expect map values to be redacted and map keys to remain visible.

Do not put sensitive data in `HashMap` or `BTreeMap` keys unless the keys are intentionally visible after redaction.

Expect sets to redact each element and collect the results back into a set. If two different values redact to the same output, the set can shrink. Use `Vec` instead when count matters.

## JSON Values

With the `json` feature, treat `serde_json::Value` as opaque. Expect it to redact fully to `Value::String("[REDACTED]")`.

Expect the same full redaction when the field is unannotated inside a `Sensitive` type. That is intentional because arbitrary JSON may contain anything.

Convert dynamic JSON into a typed struct and derive `Sensitive` on that struct when useful redacted output is required.

## Custom Policies

Use a custom policy when none of the built-ins match the diagnostic shape you need.

```rust
#[derive(Clone, Copy)]
struct InternalId;

impl redactable::RedactionPolicy for InternalId {
    fn policy() -> redactable::TextRedactionPolicy {
        redactable::TextRedactionPolicy::keep_last(2)
    }
}
```

Prefer stricter redaction over clever partial visibility. Keep visible output only when it has a clear debugging purpose.

## Field Template

Use this template when adding a new `Sensitive` type:

```rust
#[derive(Clone, redactable::Sensitive)]
struct ExampleRecord {
    id: u64,
    #[sensitive(redactable::Pii)]
    sensitive_text_leaf: String,
    #[sensitive(redactable::Secret)]
    sensitive_string_container: Option<Vec<String>>,
    nested_sensitive_type: NestedSensitiveType,
}

#[derive(Clone, redactable::Sensitive)]
struct NestedSensitiveType {
    #[sensitive(redactable::Email)]
    email: String,
}
```

Replace each placeholder policy with the narrowest built-in or custom policy that preserves only diagnostically useful output.

## Common Mistakes

Avoid these patterns:

- Annotating a nested `Sensitive` type, such as `#[sensitive(Pii)] customer: Customer`, because it bypasses nested policies.
- Leaving sensitive string leaves unannotated, because `String` and `Cow<str>` pass through unchanged by default.
- Putting sensitive data in map keys, because keys are not redacted.
- Using `#[sensitive(redactable::Secret)]` on scalar fields, because scalar `Secret` must be a bare imported identifier.
- Using qualified primitive paths such as `std::primitive::u32`, because the derive macro does not recognize them as scalars.
- Using `&str` for structural redaction, because `Sensitive` does not support it.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-review-checklist
