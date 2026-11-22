+++
name = "csharp"
title = "C# and .NET standards pack"
prefix = "CS"
applies_to = ["*.cs"]

[[sources]]
title = "StyleCop Analyzers rules"
url = "https://github.com/DotNetAnalyzers/StyleCopAnalyzers/"
licence = "MIT"

[[sources]]
title = ".NET Framework design guidelines"
url = "https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/"
licence = "CC-BY-4.0"
+++

# C# and .NET standards pack

Rules a reviewer judges in C# code. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (`dotnet format`) and lint check (the .NET analyzers and StyleCop Analyzers, with the project's config) will own layout, naming case, file layout and the rules those analyzers enforce once the .NET profile lands (E30). This pack doesn't repeat them: where it cites a StyleCop rule, it's for the part the analyzer can't judge.

## Rules

| Rule id | Severity | Rule                                                                                                                                                                | Why/example                                                              | Source                                                                                                                                           |
| ------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| CS-001  | blocker  | Don't catch `Exception` or `SystemException` to carry on. Catch the specific types you can handle.                                                                  | A broad catch hides bugs along with the failure you meant.               | [.NET: Exceptions](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/exceptions)                                               |
| CS-002  | blocker  | Dispose every `IDisposable` you own, with `using`.                                                                                                                  | Handles and connections leak until the finalizer runs, if it ever does.  | [.NET: Dispose pattern](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/dispose-pattern)                                     |
| CS-003  | blocker  | Don't throw from `Dispose`, from finalizers, or from `finally` blocks.                                                                                              | A throw there replaces the exception that was already on its way out.    | [.NET: Dispose pattern](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/dispose-pattern)                                     |
| CS-004  | major    | Check public arguments at the start, and throw `ArgumentNullException`, `ArgumentOutOfRangeException` or `ArgumentException`.                                       | The caller learns which argument was wrong, before anything has changed. | [.NET: Using standard exception types](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/using-standard-exception-types)       |
| CS-005  | major    | Report failures by throwing exceptions, not by returning error codes.                                                                                               | An error code is easy to ignore; an exception isn't.                     | [.NET: Exception throwing](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/exception-throwing)                               |
| CS-006  | major    | Use a class unless the type is small, short-lived, immutable and value-like. Then a struct can fit.                                                                 | Large or mutable structs copy surprisingly and cost performance.         | [.NET: Choosing between class and struct](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/choosing-between-class-and-struct) |
| CS-007  | major    | Properties are cheap and have no side effects. Use a method when the work is slow or changes state.                                                                 | Callers read properties freely, in loops and debuggers.                  | [.NET: Property design](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/property)                                            |
| CS-008  | major    | Expose collections as read-only (`IReadOnlyList<T>`, `ReadOnlyCollection<T>`) unless callers must change them.                                                      | Callers can't break your invariants through a list you handed out.       | [.NET: Guidelines for collections](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/guidelines-for-collections)               |
| CS-009  | major    | Return an empty collection, never `null`, from a member that returns a collection.                                                                                  | Callers can loop without a null check.                                   | [.NET: Guidelines for collections](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/guidelines-for-collections)               |
| CS-010  | major    | Use an enum for a closed set of choices, rather than `bool` or `int` parameters. Use `[Flags]` only for real bit sets.                                              | `Open(path, FileMode.Append)` reads; `Open(path, true)` doesn't.         | [.NET: Enum design](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/enum)                                                    |
| CS-011  | major    | Implement the dispose pattern for types that hold unmanaged resources: `Dispose(bool)`, or seal the type.                                                           | Subclasses and finalizers then clean up correctly.                       | [.NET: Dispose pattern](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/dispose-pattern)                                     |
| CS-012  | minor    | Avoid `out` and `ref` parameters in public APIs. Return a type, or a tuple, instead.                                                                                | Return values are easier to use and to read.                             | [.NET: Parameter design](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/parameter-design)                                   |
| CS-013  | minor    | Names say what a thing means, not its type. No Hungarian notation.                                                                                                  | `retryCount`, not `iRetryCount`.                                         | [.NET: General naming conventions](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/general-naming-conventions)               |
| CS-014  | minor    | Avoid abbreviations and acronyms in names, unless they're widely known.                                                                                             | `GetWindow`, not `GetWin`.                                               | [.NET: General naming conventions](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/general-naming-conventions)               |
| CS-015  | minor    | Name events with verbs, using tense for timing (`Closing`, `Closed`), and use `EventHandler<T>` for handlers.                                                       | Subscribers can tell before-events from after-events.                    | [.NET: Event design](https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/event)                                                  |
| CS-016  | minor    | Every public type and member has an XML documentation comment that says what the code doesn't. SA1600 checks that it's there; review checks that it says something. | "Gets the name" on `Name` adds nothing.                                  | [StyleCop SA1600](https://github.com/DotNetAnalyzers/StyleCopAnalyzers/blob/master/documentation/SA1600.md)                                      |
| CS-017  | minor    | A parameter's documentation says what it means and which values are valid, not its type. SA1611 checks that it's there.                                             | `<param name="timeout">Milliseconds to wait; 0 means no wait.</param>`   | [StyleCop SA1611](https://github.com/DotNetAnalyzers/StyleCopAnalyzers/blob/master/documentation/SA1611.md)                                      |
