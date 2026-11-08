# Spec

What is being built, and why. Prose, not a list. **Ceiling {{CEILING_SPEC}}
tokens**, substituted by new-project.ps1 from the context-budget.json the
driver actually enforces, so this figure cannot disagree with it.

This file is the anchor. Every plan is checked against it, including by the
audit pass, which is asked whether anything the spec requires was never
delivered by any plan.

Replace this text.

## Language and conventions

Name them here, because the coding rules do not choose a language. The model follows this section exactly.

- **Language and version:** (for example, a language name and its minimum version).
- **Case of names:** functions (a verb followed by its complement), types, constants, variables.
- **Documentation comment:** the form that carries Purpose, Inputs, Outputs and Raises.
- **Tests:** the folder, the file name pattern, and the one command that runs them.
- **Format and lint commands,** if any: they must pass before a step is ticked.
