---
name: redactable-field-policies
description: "Use when adding or reviewing redactable field annotations to choose safe policies for leaves, containers, scalars, JSON, maps, and sets."
metadata:
  skillcatalog/display_name: "Redactable Field Policies"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-09-16T00:00:00Z"
---
# Redactable Field Policies

Targets `redactable` 0.13. Use when adding or reviewing `#[sensitive(...)]` and `#[not_sensitive]` fields.

Two rules govern every field:

1. **Every structural field needs a declaration.** No annotation and no declared type is a compile error.
2. **Annotate sensitive leaves, not sensitive containers.** A nested type that derives redaction runs its own policies.

## Deciding Each Field

| The field holds | Use |
|---|---|
| A sensitive leaf (`String`, `Cow<str>`, scalar) | `#[sensitive(Policy)]` |
| A leaf that must carry its policy wherever it goes | `SensitiveValue<T, P>`, unannotated |
| A genuinely public value, including a foreign type | `#[not_sensitive]` |
| A nested type that derives redaction | leave it unannotated |
| A foreign value at a `Redactable`-bounded boundary, reviewed as wholly public | `BypassRedaction<T>`, unannotated |

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct UserProfile {
    #[not_sensitive]
    user_id: u64,
    #[sensitive(redactable::Pii)]
    full_name: String,
    #[sensitive(redactable::Email)]
    email: String,
    settings: Settings,     // nested derive — unannotated
}
```

**Must-do:** Choose `#[not_sensitive]` on evidence about the data, not to clear a compile error. The compiler forces a decision; it does not check that the decision is right.

## Built-In Policies

| Policy | Use for | Output |
|---|---|---|
| `Secret` | passwords, keys, raw secrets, scalars | `[REDACTED]`; scalars become `0` / `0.0` / `false` / `'*'` |
| `Token` | API keys, bearer tokens, session tokens | keeps last 4 |
| `Email` | email addresses | keeps first 2 local-part chars and the domain |
| `CreditCard` | card numbers or PANs | keeps last 4 |
| `Pii` | names, addresses, general personal data | keeps last 2 |
| `PhoneNumber` | phone numbers | keeps last 4 |
| `BlockchainAddress` | wallet addresses | keeps last 6 |
| `IpAddress` on text | IP strings | keeps last 4 |
| `IpAddress` on a bare typed IP (`ip-address` feature) | `IpAddr`, `Ipv4Addr`, `Ipv6Addr`, `SocketAddr` | zeroes all but the last IPv4 octet or last IPv6 segment; IPv4-mapped IPv6 uses the IPv4 rule; `SocketAddr` keeps its port |

The two `IpAddress` rows are not equivalent. On a short address the text rule discloses more: `"1.2.3.4"` as text keeps the last 4 characters — `"***.3.4"`, two octets — where the typed value yields `"0.0.0.4"`. Store IPs as `std::net` types when you want the octet rule.

**[guarantee] Short values are fully masked.** Keep-based policies fail closed: a value at or below the keep window is masked entirely, never revealed. `Email` applies the same rule to a short local part, and empty strings redact to `[REDACTED]`. Do not write tests expecting short values to pass through.

Use `Secret` when partial visibility has no diagnostic value. Reach for a keep-based policy only when the visible suffix or email domain genuinely helps debugging.

## Scalars

Scalars accept `Secret` and no other built-in policy. A custom policy works too when it declares `type Kind = SecretPolicyKind;` — that kind, not the name, is what admits scalars.

```rust
use redactable::{Secret, Sensitive};

#[derive(Clone, serde::Serialize, Sensitive)]
struct LoginAttempt {
    #[sensitive(Secret)]
    failed_count: u32,
    #[sensitive(Secret)]
    enabled: bool,
}
```

Policy dispatch is type-directed, so the policy path can be written any way that resolves: bare `Secret`, `redactable::Secret`, or a renamed import all work. Field types can be written as `u32`, `std::primitive::u32`, or a local type alias.

**[guarantee]** Scalar redaction yields: integers `0`, floats `0.0`, `bool` `false`, `char` `'*'`.

**[guarantee]** `NonZeroU32` and the other `NonZero*` types cannot be policy-annotated, because redaction would have to produce zero. Use `#[not_sensitive]`, or change the field to the plain integer type.

## Containers

Apply `#[sensitive(Policy)]` to the field and the policy recurses to the contained leaves:

- `Option<String>`
- `Vec<String>`, `VecDeque<String>`, `[String; N]`
- `Box<String>`, `Arc<String>`, `Rc<String>`
- `Result<T, E>`, `RefCell<String>`
- maps and sets
- nested combinations such as `Option<VecDeque<String>>`

**Must-do:** Do not confuse this list with the structural traversal list. Tuples, `Mutex`, and `RwLock` delegate during *traversal* of declared contents, but they accept no `#[sensitive(Policy)]` annotation — a tuple fails on `PolicyField`, and the two locks fail on `Clone`. `Cell<T>` is listed by the crate but requires `T: Copy`, which no policy-applicable type satisfies, so it is unreachable in practice.

Wrapping the inner value in `SensitiveValue<T, P>` fixes only some of these, so check the shape before reaching for it:

| Shape | `SensitiveValue` inside it |
|---|---|
| tuple, `RefCell` | works |
| `Cell` | no — `Cell` needs `Copy`, and `SensitiveValue` is not `Copy` |
| `Mutex`, `RwLock` | no — `Sensitive` needs `Clone` on the whole type, and neither lock is `Clone` |

For a lock, log a separate view type built from the guard rather than deriving redaction on the lock itself.

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct ContactList {
    #[sensitive(redactable::Email)]
    emails: Vec<String>,
    #[sensitive(redactable::Secret)]
    recovery_codes: Option<Vec<String>>,
}
```

For a container of already-declared values, leave the field unannotated and let traversal delegate. Traversal forwards the declaration requirement too: `Vec<User>` is fine when `User` derives redaction, and `Vec<String>` is still a compile error.

**Must-do:** Do not annotate typed IPs through containers. `#[sensitive(IpAddress)]` accepts a typed IP only as a **bare** field. Inside a container, wrap each value: `Option<SensitiveValue<std::net::IpAddr, redactable::IpAddress>>`. IP policies do recurse through text values.

**Must-do:** Use owned `String` or `Cow<str>`. `&str` is not supported for structural redaction.

**[guarantee]** A field holding `Arc<T>` or `Rc<T>` inside a `Sensitive` type needs serde's `rc` feature in your crate, a handwritten `Serialize`, or `#[serde(skip)]`. `Sensitive` requires `Serialize`, and serde does not serialize shared pointers by default. `redactable` does not enable `serde/rc` for you.

## Maps And Sets

**[guarantee]** Map values are redacted. **Map keys are not.**

```rust
use redactable::{Pii, Redactable, Secret, Sensitive};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, serde::Serialize, Sensitive)]
struct Record {
    #[sensitive(Secret)]
    attributes: BTreeMap<String, String>,
    #[sensitive(Pii)]
    names: BTreeSet<String>,
}

let redacted = Record {
    attributes: BTreeMap::from([("customer_email".into(), "alice@example.com".into())]),
    names: BTreeSet::from(["Xy".to_string(), "Zy".to_string(), "Qy".to_string()]),
}
.redact();

// The value is redacted. The key is not — it still names the data it held.
assert_eq!(redacted.attributes["customer_email"], "[REDACTED]");

// All three names are at the keep window, so all three mask to the same text
// and the set silently collapses from 3 entries to 1.
assert_eq!(redacted.names, BTreeSet::from(["**".to_string()]));
```

**Must-do:** Never put sensitive data in a map key.

**[guarantee]** Sets redact each element and collect back into a set. If two values redact to the same output, the set shrinks, as above. Use `Vec` when cardinality matters.

## JSON Values

**[guarantee]** `serde_json::Value` is an opaque leaf. Left unannotated it redacts fully to `Value::String("[REDACTED]")` through `.redact()` and every adapter, without traversing its structure. That default is deliberate: arbitrary JSON may contain anything.

**Must-do:** `#[not_sensitive]` overrides that default and keeps the payload raw, because it skips traversal like any other field. A `#[not_sensitive] payload: serde_json::Value` logs everything inside it. Reserve it for JSON you have actually inspected, and remember that the values inside can change without the annotation changing.

**[guarantee]** Generated `Debug` is annotation-driven, so an **unannotated** `serde_json::Value` field prints its raw contents through `serde_json`'s own `Debug` even though `.redact()` collapses it. Annotate it `#[sensitive(Secret)]` when generated `Debug` must also hide it.

Convert dynamic JSON into a typed struct and derive `Sensitive` on that struct when useful redacted output is required.

This behavior comes with the `redaction` feature, which is on by default and carries `serde` and `serde_json`. The old `json` feature is a compatibility alias for it.

## Custom Policies

Use a custom policy when no built-in matches the diagnostic shape you need. A custom policy **must** declare its structural kind.

```rust
use redactable::{RedactionPolicy, TextPolicyKind, TextRedactionPolicy};

#[derive(Clone, Copy)]
struct InternalId;

impl RedactionPolicy for InternalId {
    type Kind = TextPolicyKind;

    fn policy() -> TextRedactionPolicy {
        TextRedactionPolicy::keep_last(2)
    }
}
```

Omitting `type Kind` fails with `E0046: not all trait items implemented, missing: `Kind``. `TextPolicyKind` is the right choice for text policies; `SecretPolicyKind` additionally covers bare scalars. `IpAddressPolicyKind` is reserved for the built-in IP behavior.

Prefer stricter redaction over clever partial visibility. Custom keep-based policies inherit the fail-closed rule.

## Field Template

```rust
use redactable::{Email, Pii, Secret, Sensitive, SensitiveValue, Token};

#[derive(Clone, serde::Serialize, Sensitive)]
struct ExampleRecord {
    #[not_sensitive]
    id: u64,
    #[sensitive(Pii)]
    sensitive_text_leaf: String,
    #[sensitive(Secret)]
    sensitive_string_container: Option<Vec<String>>,
    #[sensitive(Secret)]
    attempt_count: u32,
    api_key: SensitiveValue<String, Token>,
    nested: NestedSensitiveType,
    payload: serde_json::Value,
}

#[derive(Clone, serde::Serialize, Sensitive)]
struct NestedSensitiveType {
    #[sensitive(Email)]
    email: String,
}
```

Replace each policy with the narrowest one that preserves only diagnostically useful output.

## Common Mistakes

- Annotating a nested declared type (`#[sensitive(Pii)] customer: Customer`) — fails on `PolicyField<Pii>`; leave it unannotated.
- Reaching for `#[not_sensitive]` to clear a compile error on a field that holds user data.
- Putting sensitive data in map keys, because keys are never redacted.
- Annotating a typed IP inside `Option`/`Vec`; wrap it in `SensitiveValue<_, IpAddress>` instead.
- Using `&str` for structural redaction.
- Writing a custom `RedactionPolicy` without `type Kind`.
- Annotating an enum *variant* instead of its fields — variant-level `#[sensitive(...)]` and `#[not_sensitive]` are compile errors.
- Assuming generated `Debug` has one shape. `Sensitive` prints a flat `"[REDACTED]"` per annotated field, so it hides policy output; `SensitiveDisplay` and `SensitiveDual` print the redacted template, which *carries* policy output and renders `#[not_sensitive]` fields raw.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-review-checklist
