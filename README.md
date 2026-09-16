# Redactable Skills

Public SkillCatalog catalog for reusable Rust `redactable` crate guidance.

The catalog contains redactable-specific skills, one stack, and one bundle:

- `skills/redactable-*`
- `stacks/redactable.yaml`
- `bundles/redactable-skills.yaml`

## Install

```sh
skc catalog add https://github.com/sformisano/redactable-skills.git
```

## Contents

The `redactable` stack covers the core model, derive selection, field policies, wrappers and escape hatches, logging boundaries, and review checklist for Rust code that uses the `redactable` crate.

## Crate version

These skills target `redactable` 0.13. The crate changed its core model in 0.12 — every field now needs an explicit redaction declaration — and renamed most of its output and wrapper API. Guidance written for 0.10 or earlier does not apply. The core model and review checklist skills list the renamed and removed APIs for code still on the old surface.

Every Rust example in these skills is compiled and run against that pinned release by `harness/check_examples.py`, which CI runs on every push and weekly. A separate advisory job reports when a newer release exists, since a pinned check cannot notice one on its own. See [VALIDATION.md](VALIDATION.md) for how the content was verified and what remains unverified.
