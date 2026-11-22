+++
name = "javascript"
title = "JavaScript standards pack"
prefix = "JS"
applies_to = ["*.js", "*.jsx", "*.mjs", "*.cjs"]

[[sources]]
title = "Google JavaScript Style Guide"
url = "https://google.github.io/styleguide/jsguide.html"
licence = "CC-BY-3.0"
+++

# JavaScript standards pack

Rules a reviewer judges in JavaScript code. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (`prettier`) owns layout, and its lint check (`eslint`, with the project's config) owns the mechanical rules. This pack doesn't repeat them. Its links name the guide's section; they point to the guide's page, because its section anchors weren't checked.

## Rules

| Rule id | Severity | Rule                                                                                                                                          | Why/example                                                          | Source                                                                                             |
| ------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| JS-001  | blocker  | Throw only `Error` objects: `new Error(...)` or a subclass, never strings or plain objects.                                                   | A thrown string has no stack trace.                                  | [Google JS: Exceptions](https://google.github.io/styleguide/jsguide.html)                          |
| JS-002  | blocker  | An empty `catch` block has a comment that says why ignoring the error is safe.                                                                | Otherwise a failure disappears without a trace.                      | [Google JS: Empty catch blocks](https://google.github.io/styleguide/jsguide.html)                  |
| JS-003  | blocker  | Never run strings as code: no `eval` and no `new Function(string)`.                                                                           | Code built from data is an injection waiting to happen.              | [Google JS: Disallowed features](https://google.github.io/styleguide/jsguide.html)                 |
| JS-004  | blocker  | Never add to or change built-in objects or their prototypes.                                                                                  | A patched `Array.prototype` changes every library in the page.       | [Google JS: Modifying builtin objects](https://google.github.io/styleguide/jsguide.html)           |
| JS-005  | major    | Declare with `const`, or `let` when you reassign. Never `var`.                                                                                | `var` is function-scoped and hoisted, so it leaks out of blocks.     | [Google JS: Local variable declarations](https://google.github.io/styleguide/jsguide.html)         |
| JS-006  | major    | Compare with `===` and `!==`. The one exception is `== null`, to catch both `null` and `undefined`.                                           | `==` converts types first: `'' == 0` is true.                        | [Google JS: Equality checks](https://google.github.io/styleguide/jsguide.html)                     |
| JS-007  | major    | Iterate arrays with `for...of` or array methods. Use `for...in` only on dictionary-style objects.                                             | `for...in` walks string keys, inherited ones included.               | [Google JS: for-in loops](https://google.github.io/styleguide/jsguide.html)                        |
| JS-008  | major    | Use `class` syntax. Don't build classes by assigning to `prototype` by hand.                                                                  | Classes are clearer, and the tools understand them.                  | [Google JS: Classes](https://google.github.io/styleguide/jsguide.html)                             |
| JS-009  | major    | Don't define getter or setter properties. Use ordinary methods.                                                                               | A property read that does work, or changes state, surprises callers. | [Google JS: Getters and setters](https://google.github.io/styleguide/jsguide.html)                 |
| JS-010  | major    | Never create wrapper objects for primitives: no `new String`, `new Number` or `new Boolean`.                                                  | `new Boolean(false)` is truthy.                                      | [Google JS: Wrapper objects for primitive types](https://google.github.io/styleguide/jsguide.html) |
| JS-011  | major    | Use named exports, not default exports.                                                                                                       | A named export has the same name at every import site.               | [Google JS: Exports](https://google.github.io/styleguide/jsguide.html)                             |
| JS-012  | minor    | Document exported functions and classes with JSDoc, including `@param` and `@return` where the types aren't obvious.                          | In plain JavaScript, JSDoc is where the types live.                  | [Google JS: JSDoc](https://google.github.io/styleguide/jsguide.html)                               |
| JS-013  | minor    | Use arrow functions for nested functions that need the outer `this`, rather than `bind` or `const self = this`.                               | Arrow functions keep `this` without extra plumbing.                  | [Google JS: Arrow functions](https://google.github.io/styleguide/jsguide.html)                     |
| JS-014  | minor    | Use lowerCamelCase for methods and variables, UpperCamelCase for classes, and CONSTANT_CASE only for deeply immutable module-level constants. | The case tells the reader what kind of thing a name is.              | [Google JS: Naming](https://google.github.io/styleguide/jsguide.html)                              |
| JS-015  | minor    | Use rest parameters (`...args`), never `arguments`.                                                                                           | Rest parameters are real arrays, and they show in the signature.     | [Google JS: Parameters](https://google.github.io/styleguide/jsguide.html)                          |
| JS-016  | minor    | Use template literals rather than long chains of string concatenation.                                                                        | `${name} has ${count} items` reads at a glance.                      | [Google JS: Template literals](https://google.github.io/styleguide/jsguide.html)                   |
| JS-017  | minor    | A `switch` has a `default` case, even an empty one with a comment.                                                                            | The reader sees that the other values were considered.               | [Google JS: Switch statements](https://google.github.io/styleguide/jsguide.html)                   |
