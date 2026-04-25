# Mock Kind

> **Tooltip:** Type discriminator on a test_case_mock: tool / source / target. Step-level mocks live on MockContext only.

## Definition

An enum on the `test_case_mock` table discriminating which kind of interaction is being mocked. `tool` mocks an Agent tool by name; `source` mocks a Task source binding by input field; `target` mocks a Task write target as expectation-only. Step-level mocks (whole-step short-circuit) are runtime-only — they live on MockContext, not on test_case_mock.

## See also

- [Mock Context](mock-context.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
