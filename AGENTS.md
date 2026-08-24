# GenericVM Project Instructions

## VM instruction-set policy

Keep the core VM instruction set as small and simple as possible so VM implementations remain easy to build and maintain.

- Prefer implementing language features by composing existing VM instructions whenever that is reasonably practical.
- Do not add, propose as implemented, or silently introduce a new core VM/IR instruction without the user's explicit approval.
- If composition using existing instructions would be excessively complex, first explain the required sequence, the complexity or limitations, and the proposed new instruction. Wait for explicit user approval before adding it.
- More complex VM instructions are a language and VM design decision reserved for the user, not an implementation detail the agent may decide independently.
- Tests, compiler convenience, performance, or reduced compiler code are not by themselves sufficient justification for expanding the VM instruction set.

This policy is a mandatory project invariant and applies across all future tasks and conversations in this repository.
