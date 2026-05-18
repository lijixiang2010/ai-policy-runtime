# CMake Best Practices Skill Pack

`cmake.best_practices` gives agents task-aware guidance for modern CMake work:
target-based project structure, usage requirements, dependency integration,
install/export packaging, presets, toolchains, tests, and quality tooling.

## Structure

### Core

These rules appear when the task is about project structure or target contracts.
They keep CMake guidance centered on modern targets without forcing target
details into unrelated preset, test, or packaging tasks.

- Target model: define libraries and executables as explicit targets, attach
  build requirements to those targets, and avoid broad directory-global state.
- Usage requirements: use `PRIVATE`, `PUBLIC`, and `INTERFACE` according to the
  target contract so consumers receive exactly the requirements they need.

### Task Modules

These rules activate only when the task names the relevant work.

- Compiler options: prefer compile features and generator expressions over raw
  global flags, keep warnings-as-errors opt-in, and handle multi-config
  generators correctly.
- Sources and generated files: keep primary sources explicit, generated files
  declared, and custom commands portable.
- Dependencies: prefer imported or project targets, use package discovery when
  appropriate, and pin fetched source dependencies.
- Quality tooling: expose tests through CTest and keep sanitizers, coverage,
  static analysis, and strict warnings opt-in through presets or targets.

### Advanced Or Downstream Workflows

These rules are intentionally secondary. They are included when requested, but
they should not crowd the main prompt for ordinary CMake modernization tasks.

- Distribution: install and export targets, keep packages relocatable, and build
  binary packaging on top of correct install rules.
- Reproducibility: use out-of-source builds, shared project presets, local user
  presets, and explicit toolchain files for cross-compilation.
- Options and modules: prefix project options and keep reusable CMake code scoped
  through functions or modules when the task asks for reusable build logic.

## Deferred Topics

The pack intentionally keeps Apple bundles, Doxygen details, large super-build
or ExternalProject orchestration, and CPack installer internals out of the main
prompt unless future task-specific skills need them.

## Sources

The pack is synthesized from:

- CMake Best Practices: Upgrade your C++ builds with CMake for maximum
  efficiency and scalability, Dominik Berner and Mustafa Kemal Gilor.
- Effective Modern CMake notes by mbinna:
  https://gist.github.com/mbinna/c61dbb39bca0e4fb7d1f73b0d66a4fd1
