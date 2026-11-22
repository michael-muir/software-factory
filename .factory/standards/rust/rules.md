+++
name = "rust"
title = "Rust standards pack"
prefix = "RS"
applies_to = ["*.rs"]

[[sources]]
title = "Rust API Guidelines"
url = "https://rust-lang.github.io/api-guidelines/"
licence = "MIT OR Apache-2.0"
+++

# Rust standards pack

Rules a reviewer judges in Rust code. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (`rustfmt`) and lint check (`clippy`, with the project's config) will own layout, naming case and the mechanical rules once the Rust profile lands (E30). The compiler's own warnings cover the rest. This pack doesn't repeat them.

## Rules

| Rule id | Severity | Rule                                                                                                                            | Why/example                                                         | Source                                                                                                                    |
| ------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| RS-001  | blocker  | Error types are meaningful and well-behaved: they implement `std::error::Error`, `Display` and `Debug`, and are never `()`.     | Callers can't report or match on an error that says nothing.        | [Rust API Guidelines: C-GOOD-ERR](https://rust-lang.github.io/api-guidelines/interoperability.html#c-good-err)            |
| RS-002  | blocker  | Destructors never fail: no panics in `Drop`.                                                                                    | A panic while unwinding aborts the process.                         | [Rust API Guidelines: C-DTOR-FAIL](https://rust-lang.github.io/api-guidelines/dependability.html#c-dtor-fail)             |
| RS-003  | blocker  | Functions validate their arguments, preferably with types that make bad values impossible, otherwise with checks.               | An invalid value that gets in surfaces far from its cause.          | [Rust API Guidelines: C-VALIDATE](https://rust-lang.github.io/api-guidelines/dependability.html#c-validate)               |
| RS-004  | blocker  | Every `unsafe` function documents its safety requirements in a `# Safety` section, and every `unsafe` block says why they hold. | Undefined behaviour is one wrong assumption away.                   | [Rust API Guidelines: C-FAILURE](https://rust-lang.github.io/api-guidelines/documentation.html#c-failure)                 |
| RS-005  | major    | Conversions follow the naming convention for their cost: `as_` is free, `to_` is expensive, `into_` consumes.                   | The name tells the caller what the call costs.                      | [Rust API Guidelines: C-CONV](https://rust-lang.github.io/api-guidelines/naming.html#c-conv)                              |
| RS-006  | major    | Public types eagerly implement the common traits that make sense: `Debug`, `Clone`, `PartialEq`, `Eq`, `Hash`, `Default`.       | Downstream crates can't add them later.                             | [Rust API Guidelines: C-COMMON-TRAITS](https://rust-lang.github.io/api-guidelines/interoperability.html#c-common-traits)  |
| RS-007  | major    | All public types implement `Debug`.                                                                                             | Users can't log or inspect what they can't print.                   | [Rust API Guidelines: C-DEBUG](https://rust-lang.github.io/api-guidelines/debuggability.html#c-debug)                     |
| RS-008  | major    | Use newtypes for distinctions the type system should hold, such as units and ids.                                               | `Meters(5.0)` can't be passed where `Seconds` is expected.          | [Rust API Guidelines: C-NEWTYPE](https://rust-lang.github.io/api-guidelines/type-safety.html#c-newtype)                   |
| RS-009  | major    | Arguments carry meaning through types, not `bool` or `Option` flags.                                                            | `open(path, Mode::ReadOnly)` reads; `open(path, true)` doesn't.     | [Rust API Guidelines: C-CUSTOM-TYPE](https://rust-lang.github.io/api-guidelines/type-safety.html#c-custom-type)           |
| RS-010  | major    | Struct fields are private unless the struct is plain data.                                                                      | Private fields can change without breaking callers.                 | [Rust API Guidelines: C-STRUCT-PRIVATE](https://rust-lang.github.io/api-guidelines/future-proofing.html#c-struct-private) |
| RS-011  | major    | Let the caller decide where data is copied and placed: take ownership only when you need it, and borrow otherwise.              | Callers avoid needless clones.                                      | [Rust API Guidelines: C-CALLER-CONTROL](https://rust-lang.github.io/api-guidelines/flexibility.html#c-caller-control)     |
| RS-012  | major    | Only smart pointers implement `Deref`.                                                                                          | `Deref` on other types makes method lookup surprising.              | [Rust API Guidelines: C-DEREF](https://rust-lang.github.io/api-guidelines/predictability.html#c-deref)                    |
| RS-013  | major    | Destructors that may block have a non-blocking alternative, such as an explicit `close`.                                        | Callers need a way to handle the failure or the wait.               | [Rust API Guidelines: C-DTOR-BLOCK](https://rust-lang.github.io/api-guidelines/dependability.html#c-dtor-block)           |
| RS-014  | minor    | Getters are named after the field, without a `get_` prefix.                                                                     | `len()`, not `get_len()`.                                           | [Rust API Guidelines: C-GETTER](https://rust-lang.github.io/api-guidelines/naming.html#c-getter)                          |
| RS-015  | minor    | Seal traits that downstream crates shouldn't implement.                                                                         | You can then add methods without a breaking change.                 | [Rust API Guidelines: C-SEALED](https://rust-lang.github.io/api-guidelines/future-proofing.html#c-sealed)                 |
| RS-016  | minor    | Expose intermediate results that callers would otherwise compute again.                                                         | A search that returns the position saves a second search.           | [Rust API Guidelines: C-INTERMEDIATE](https://rust-lang.github.io/api-guidelines/flexibility.html#c-intermediate)         |
| RS-017  | minor    | Examples in docs use `?`, not `unwrap()`.                                                                                       | Readers copy examples, so examples should show real error handling. | [Rust API Guidelines: C-QUESTION-MARK](https://rust-lang.github.io/api-guidelines/documentation.html#c-question-mark)     |
| RS-018  | minor    | Crate-level docs are thorough and include examples.                                                                             | The crate root is the first page users read.                        | [Rust API Guidelines: C-CRATE-DOC](https://rust-lang.github.io/api-guidelines/documentation.html#c-crate-doc)             |
| RS-019  | minor    | Use a builder to construct values with many optional parts.                                                                     | A builder reads better than a constructor with eight arguments.     | [Rust API Guidelines: C-BUILDER](https://rust-lang.github.io/api-guidelines/type-safety.html#c-builder)                   |
| RS-020  | minor    | Constructors are static inherent methods, usually `new`.                                                                        | Users find them where they expect.                                  | [Rust API Guidelines: C-CTOR](https://rust-lang.github.io/api-guidelines/predictability.html#c-ctor)                      |
