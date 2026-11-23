+++
name = "typescript"
title = "TypeScript standards pack"
prefix = "TS"
applies_to = ["*.ts", "*.tsx", "*.mts", "*.cts"]

[[sources]]
title = "Google TypeScript Style Guide"
url = "https://google.github.io/styleguide/tsguide.html"
licence = "CC-BY-3.0"
+++

# TypeScript standards pack

Rules a reviewer judges in TypeScript code. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (`prettier`) owns layout. Its lint check (`eslint`, with the project's config) owns the mechanical rules, and its types check (`tsc --noEmit`) owns type errors. This pack doesn't repeat them. Its links name the guide's section; they point to the guide's page, because its section anchors weren't checked.

## Rules

| Rule id | Severity | Rule                                                                                                                                             | Why/example                                                                         | Source                                                                                             |
| ------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| TS-001  | blocker  | Don't use `any` to get past the compiler. Write the real type, or use `unknown` and narrow it.                                                   | `any` switches checking off for every value it reaches.                             | [Google TS: the any type](https://google.github.io/styleguide/tsguide.html)                        |
| TS-002  | blocker  | Throw only `Error` objects: `new Error(...)` or a subclass, never strings or plain objects.                                                      | A thrown string has no stack trace.                                                 | [Google TS: Exceptions](https://google.github.io/styleguide/tsguide.html)                          |
| TS-003  | blocker  | Don't silence the compiler with `@ts-ignore`, `@ts-expect-error` or `@ts-nocheck` in production code.                                            | The error is still there; only the message is gone.                                 | [Google TS: @ts-ignore](https://google.github.io/styleguide/tsguide.html)                          |
| TS-004  | blocker  | An empty `catch` block has a comment that says why ignoring the error is safe.                                                                   | Otherwise a failure disappears without a trace.                                     | [Google TS: Empty catch blocks](https://google.github.io/styleguide/tsguide.html)                  |
| TS-005  | major    | Avoid type assertions (`as T`) and non-null assertions (`x!`). Prefer a runtime check that narrows the type, and explain any assertion you keep. | An assertion is a promise the compiler can't check.                                 | [Google TS: Type and non-nullability assertions](https://google.github.io/styleguide/tsguide.html) |
| TS-006  | major    | Use named exports, not default exports.                                                                                                          | A named export has the same name at every import site, and a typo fails to compile. | [Google TS: Exports](https://google.github.io/styleguide/tsguide.html)                             |
| TS-007  | major    | Don't export mutable bindings (`export let`). Export a function, or a `const` object, instead.                                                   | Importers can't tell when the value changes under them.                             | [Google TS: Mutable exports](https://google.github.io/styleguide/tsguide.html)                     |
| TS-008  | major    | Use ES modules: no `namespace` blocks and no `require()`.                                                                                        | Modules give real dependency edges that tools understand.                           | [Google TS: Modules](https://google.github.io/styleguide/tsguide.html)                             |
| TS-009  | major    | Mark a property `readonly` when nothing reassigns it after construction.                                                                         | The reader and the compiler both know it can't change.                              | [Google TS: Use readonly](https://google.github.io/styleguide/tsguide.html)                        |
| TS-010  | major    | Getters don't change observable state.                                                                                                           | A read that writes surprises every caller.                                          | [Google TS: Getters and setters](https://google.github.io/styleguide/tsguide.html)                 |
| TS-011  | major    | Iterate arrays with `for...of` or array methods, never `for...in`.                                                                               | `for...in` walks string keys, inherited ones included.                              | [Google TS: Iterating objects](https://google.github.io/styleguide/tsguide.html)                   |
| TS-012  | major    | Compare with `===` and `!==`. The one exception is `== null`, to catch both `null` and `undefined`.                                              | `==` converts types first: `'' == 0` is true.                                       | [Google TS: Equality checks](https://google.github.io/styleguide/tsguide.html)                     |
| TS-013  | minor    | Use lowerCamelCase for values and UpperCamelCase for types, with no `_` prefix or suffix for privacy and no `I` prefix on interfaces.            | Privacy belongs to `private`, not to the name.                                      | [Google TS: Identifiers](https://google.github.io/styleguide/tsguide.html)                         |
| TS-014  | minor    | Prefer optional fields and parameters (`name?: string`) to adding `\| undefined` to their type.                                                  | An optional field reads as optional; `\| undefined` makes callers pass something.   | [Google TS: Optionals vs undefined](https://google.github.io/styleguide/tsguide.html)              |
| TS-015  | minor    | Don't annotate types the compiler infers trivially, as in `const count: number = 5`.                                                             | Noise hides the annotations that matter.                                            | [Google TS: Type inference](https://google.github.io/styleguide/tsguide.html)                      |
| TS-016  | minor    | Document exported APIs with JSDoc (`/** ... */`) that says what the code doesn't. Don't repeat the types in it.                                  | TypeScript already holds the types, and copies drift.                               | [Google TS: JSDoc vs comments](https://google.github.io/styleguide/tsguide.html)                   |
| TS-017  | minor    | A `switch` has a `default` case, even an empty one with a comment.                                                                               | The reader sees that the other values were considered.                              | [Google TS: Switch statements](https://google.github.io/styleguide/tsguide.html)                   |
