# Breaking-change analysis

Most defects that reach production from a reviewed change are not in the diff.
They are in the code the diff made wrong.

A careful reviewer reads the change and asks *"is this code correct?"* A senior
one reads the change and asks a different question first: *"what did this
promise to somebody else, and is that promise still true?"* The second question
is the one that catches the outage, because a broken contract does not look
broken at the site of the change. It looks fine there. It looks broken three
modules away, at runtime, for one caller nobody thought about.

This file is that second question, written down as a procedure.

## Contents

- [The blast-radius map](#the-blast-radius-map)
- [The core procedure](#the-core-procedure)
- [Strategies, policies, and interfaces](#strategies-policies-and-interfaces)
- [The other contract surfaces](#the-other-contract-surfaces)
- [What is not a breaking change](#what-is-not-a-breaking-change)
- [Severity](#severity)

## The blast-radius map

The gate precomputes, for every definition the change adds, modifies, or
removes, the places outside the change that still reference it.

It is **context, not findings**. Each entry is a caller whose assumptions this
change may have invalidated — a place you are now obliged to look before calling
the change safe. Three definitions with no external references is a leaf change
and a short review. One modified interface with thirty references is a different
kind of event, and the review should reflect that.

The map classifies each contract:

| Class | Means | The question |
|---|---|---|
| `removed` | gone or renamed | is every reference below updated, or was an alias left behind? |
| `modified` | the name survived | did the signature, defaults, or semantics survive with it? |
| `added` | new surface | does it duplicate, shadow, or conflict with what already exists? |

The map is syntactic and will miss things: dynamic dispatch, reflection, string
lookups, generated code, and anything referenced from outside the repository. A
contract with zero listed references is not proven unused. It is only *not
obviously used*.

## The core procedure

For every `removed` or `modified` contract:

**1. State the promise before.** Not the implementation — the promise. What
could a caller rely on?

- the signature: parameters, their order, which are optional, their types
- the return: shape, type, and what an empty or error result looks like
- the defaults: every value a caller gets by not passing one
- the error behavior: what it raises, when, and what it swallows
- the side effects: what it writes, logs, emits, or mutates
- the ordering and timing: is the result sorted, is the call blocking, is it
  idempotent, is it safe to retry
- the totality: does it apply to every input, or only some

**2. State the promise after.**

**3. Diff the two, then go and look.** For every difference a caller could
observe, open the referenced call sites and check whether each still holds.
Name the ones that do not — by file and line. A breaking-change finding without
a named victim is speculation.

The order matters. Reviewers who skip straight to step 3 end up reading call
sites without knowing what they are checking for, and conclude "looks fine".

## Strategies, policies, and interfaces

This is the case worth naming separately, because it is the one that breaks
silently — nothing fails to compile, no test turns red, and the damage shows up
as wrong behavior rather than an error.

When a change swaps out, extends, or re-routes an existing strategy, policy,
handler, resolver, validator, or interface:

**Check the siblings.** An interface has other implementations, and the diff
touched one of them. A new required method, a changed signature, a new
precondition, or a stricter return contract breaks every implementation the
change did not touch. Find them. They are the most commonly missed break in
this entire file, because the diff gives no hint they exist.

**Check the default.** A changed default, threshold, ordering, or selection rule
silently re-routes every caller who never opted in — which is usually all of
them. Ask who was relying on the old default, and whether anything tells them it
moved.

**Check what the old path becomes.** If the new strategy is now primary, the old
one is in one of three states, and only one of them is fine:

- still reachable and still tested — fine
- still reachable and now untested — a live path with no coverage
- unreachable — dead code that will rot, and a reader will assume it runs

**Check totality.** Behavior that used to always apply becoming conditional (or
the reverse) changes results for existing inputs while every call site compiles
unchanged. This is invisible in the diff and invisible in the type system.

**Check the selection mechanism itself.** If the change alters *how* a strategy
is chosen — a registry, a factory, a config key, a feature flag — then the blast
radius is every consumer of every strategy, not just the new one.

## The other contract surfaces

Check these when the change touches them. Each is a promise made to something
that cannot be found by searching this repository for a symbol.

**Persisted data and serialization.** Two directions, and both matter:

- can code at the *previous* version still read what this version writes?
- can *this* version read what is already stored?

A field that is now required, a renamed key, a changed enum value, or a narrowed
type breaks one of those. During a rolling deploy both versions run at once.

**Configuration.** A renamed or removed key, environment variable, or CLI flag
breaks every deployment that already sets the old one — and it breaks at
startup, in production, not in review. A fallback that reads the old name (with
a deprecation warning) is the fix.

**Public surface.** API routes, response shapes, exit codes, log formats, and
metric names. Something outside this repository may depend on any of them.
Log formats and exit codes are the ones reviewers forget: an alert rule or a
CI script is a consumer, even though it is not code you can grep for.

**Migrations.** Is it reversible? Does it lock a table that is hot? Does the
code that reads the new shape ship before, with, or after the migration that
creates it?

**Concurrency and ordering.** Assumptions callers hold but never wrote down:
that a call is idempotent, that results arrive in order, that a lock is held,
that a handler is not re-entrant.

## What is not a breaking change

Restraint here is what makes the section credible. Do not report:

- **A widely referenced symbol.** A compatible change to a popular helper is
  still compatible. Reference count is a reason to look harder, never a finding.
- **An added optional parameter** with a default that preserves existing
  behavior.
- **A widened input or narrowed output.** Accepting more, or promising more
  specifically, does not break an existing caller.
- **A new method on an interface with exactly one implementation**, which the
  change updated.
- **Internal or private surface** with no references outside the change, unless
  the language makes it reachable anyway.
- **Speculative external consumers.** "Something might call this" is not a
  finding. If nothing in the repository references it and it is not published
  surface, say so and move on.

## Severity

| Situation | Severity | Category |
|---|---|---|
| A named existing caller, sibling implementation, or stored record is wrong after this change | HIGH | `breaking-change` |
| A public contract changed with no migration path or fallback | HIGH | `breaking-change` |
| A contract changed compatibly, but a caller's assumption is now fragile or undocumented | MEDIUM | `contract-risk` |
| The old path is now unreachable or untested | MEDIUM | `dead-path` |
| A widely used contract changed and you verified the callers are fine | no finding — say what you checked | — |

HIGH requires a name. If you cannot say *which* caller breaks and *how*, it is
MEDIUM at most, and quite possibly nothing at all.
