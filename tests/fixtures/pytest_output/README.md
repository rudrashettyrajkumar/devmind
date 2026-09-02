# Recorded pytest output fixtures (E8-F2-T4)

These `.txt` files are **real** pytest 9.x output, captured verbatim, not
hand-written approximations. `PytestOutputParser` is tested against them
(`tests/services/test_pytest_parser.py`).

Every file was produced with the exact argument set `TestExecutionService` uses:

```
python -m pytest -q --tb=short -p no:cacheprovider <target>
```

run with `PYTHONPATH` pointed at `../sample_repo/src` (so `import sample.calc`
resolves), merging stdout+stderr.

| File | Target that produced it |
|---|---|
| `all_passed.txt` | two tests over `sample.calc.add`, both passing |
| `assertion_failure.txt` | two `assert add(...) == N` failures |
| `multiple_failures.txt` | three failures (assertion, assertion, `ZeroDivisionError`) + one pass |
| `fixture_error.txt` | a test whose fixture raises in setup — an `ERROR`, not a collection error |
| `import_error.txt` | a test module doing `import totally_missing_module_xyz` |
| `collection_error.txt` | a test module with a syntax error |
| `empty_suite.txt` | pytest pointed at a directory with no tests |

To regenerate, recreate the transient test modules described above against
`../sample_repo` and re-run the command. The `import_error` / `collection_error`
modules are deliberately broken and are **not** committed — they would break
collection of the real suite.
