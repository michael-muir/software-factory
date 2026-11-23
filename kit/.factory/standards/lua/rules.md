+++
name = "lua"
title = "Lua standards pack"
prefix = "LUA"
applies_to = ["*.lua"]

[[sources]]
title = "Olivine-Labs Lua Style Guide"
url = "https://github.com/Olivine-Labs/lua-style-guide"
licence = "CC0-1.0"
+++

# Lua standards pack

Rules a reviewer judges in Lua code. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (`stylua`) and lint check (`luacheck` or `selene`, with the project's config) will own layout, quotes, whitespace and the mechanical rules once the Lua profile lands (E30). This pack doesn't repeat them.

## Rules

| Rule id | Severity | Rule                                                                                                                                           | Why/example                                                                                     | Source                                                                                              |
| ------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| LUA-001 | blocker  | Declare every variable `local`. Never create a global by accident.                                                                             | A missing `local` turns a loop counter into shared state for the whole program.                 | [Lua style: Variables](https://github.com/Olivine-Labs/lua-style-guide#variables)                   |
| LUA-002 | blocker  | A module returns its table or function, and never writes to the global namespace.                                                              | Two modules that write the same global break each other.                                        | [Lua style: Modules](https://github.com/Olivine-Labs/lua-style-guide#modules)                       |
| LUA-003 | blocker  | Remember that only `false` and `nil` are false. Test `0` and `''` explicitly when they mean "none".                                            | `if count then` is true when `count` is 0.                                                      | [Lua style: Conditional Expressions](https://github.com/Olivine-Labs/lua-style-guide#conditionals)  |
| LUA-004 | major    | Validate arguments early, and return or raise an error before doing any work.                                                                  | A bad argument fails at the call, not three functions later.                                    | [Lua style: Functions](https://github.com/Olivine-Labs/lua-style-guide#functions)                   |
| LUA-005 | major    | Convert types explicitly with `tostring` and `tonumber` (with a base where it matters). Don't rely on coercion in arithmetic or concatenation. | `'10' + 1` works, and `'1e1' + 1` gives 11 too.                                                 | [Lua style: Type Casting & Coercion](https://github.com/Olivine-Labs/lua-style-guide#type-coercion) |
| LUA-006 | major    | Prefer `local function name()` to assigning anonymous functions to variables.                                                                  | Local functions can call themselves, and show their name in tracebacks.                         | [Lua style: Functions](https://github.com/Olivine-Labs/lua-style-guide#functions)                   |
| LUA-007 | major    | Copy a table before changing it if the caller still holds it.                                                                                  | Tables are passed by reference, so your change is the caller's change.                          | [Lua style: Types](https://github.com/Olivine-Labs/lua-style-guide#types)                           |
| LUA-008 | major    | Never name a parameter `arg`.                                                                                                                  | Older Lua versions give every function an implicit `arg` table, which the parameter then hides. | [Lua style: Functions](https://github.com/Olivine-Labs/lua-style-guide#functions)                   |
| LUA-009 | major    | Every module has tests.                                                                                                                        | Lua has no compiler to catch a typo in a field name; only running the code does.                | [Lua style: Testing](https://github.com/Olivine-Labs/lua-style-guide#testing)                       |
| LUA-010 | minor    | Prefer many small functions to one long one.                                                                                                   | Small functions are easier to test and to name.                                                 | [Lua style: Functions](https://github.com/Olivine-Labs/lua-style-guide#functions)                   |
| LUA-011 | minor    | Name a module's file after the module, with one module per file.                                                                               | `require('config')` then finds what the reader expects.                                         | [Lua style: Modules](https://github.com/Olivine-Labs/lua-style-guide#modules)                       |
| LUA-012 | minor    | Use dot notation for known keys, and brackets only for computed keys.                                                                          | `user.name` reads; `user['name']` hints that the key varies.                                    | [Lua style: Properties](https://github.com/Olivine-Labs/lua-style-guide#properties)                 |
| LUA-013 | minor    | Use snake_case for variables and functions, PascalCase for factories, and an `is_` or `has_` prefix for booleans.                              | The name tells the reader what kind of thing it is.                                             | [Lua style: Naming Conventions](https://github.com/Olivine-Labs/lua-style-guide#naming-conventions) |
| LUA-014 | minor    | Avoid single-letter names, except loop indices. Use `_` for values you ignore.                                                                 | `for _, user in ipairs(users)` shows which value matters.                                       | [Lua style: Naming Conventions](https://github.com/Olivine-Labs/lua-style-guide#naming-conventions) |
| LUA-015 | minor    | Write table constructors in one consistent style, and define functions outside the constructor.                                                | Long functions inside a table literal hide its shape.                                           | [Lua style: Tables](https://github.com/Olivine-Labs/lua-style-guide#tables)                         |
| LUA-016 | minor    | Assign variables at the top of their scope.                                                                                                    | The reader sees what a block works with before it starts.                                       | [Lua style: Variables](https://github.com/Olivine-Labs/lua-style-guide#variables)                   |
| LUA-017 | minor    | Prefer positive conditions to negated ones with an `else`.                                                                                     | `if ready then a() else b() end` reads better than `if not ready then b() else a() end`.        | [Lua style: Conditional Expressions](https://github.com/Olivine-Labs/lua-style-guide#conditionals)  |
