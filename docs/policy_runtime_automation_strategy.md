# Policy Runtime 自动化接入策略

## 摘要

Policy Runtime 的核心职责不是静态维护一份通用规则文档，而是在每次任务进入 Agent 执行链路之前，根据当前输入、任务上下文、项目环境和可用 Skills 动态生成本次任务真正生效的 Effective Rules，并将其自动注入到 Codex、Claude Code 或其他 Coding Agent 的可读取上下文中。

该策略的重点在于：Effective Rules 不是一次性产物，而是具有任务级、步骤级、文件级生命周期的动态策略结果。Policy Runtime 应作为 Agent Harness 的组成部分，位于 Agent 执行前、执行中和执行后，分别承担规则生成、上下文注入、过程约束、结果验证和违规修复等职责。

本文档描述一套可工程化落地的自动化接入策略，覆盖触发时机、结果存放、Agent 注入方式、Codex / Claude Code 适配、CLI 工作流、状态管理、验证闭环、项目结构和演进路径。

---

## 目录

1. 问题定位
2. 基本结论
3. 核心概念
4. 总体自动化流程
5. Effective Rules 的生成时机
6. Effective Rules 的生命周期
7. 生成结果的存放位置
8. 如何将 Effective Rules 提供给 Agent
9. Codex 接入策略
10. Claude Code 接入策略
11. Wrapper 模式
12. Hook 模式
13. State 与 Trace 管理
14. Verification 与 Repair Loop
15. 推荐 CLI 设计
16. 推荐项目结构
17. 典型执行场景
18. 最小可落地版本
19. 进阶版本
20. 设计原则
21. 常见错误做法
22. 最终结论

---

## 1. 问题定位

在 Skill / Policy Runtime 体系中，用户输入不同，当前任务所需要的规则集合就不同。一个面向 C++ 低延迟代码生成的任务，与一个面向 Qt QML 登录界面设计的任务，所需要激活的 Skills、冲突裁决结果和最终规则约束完全不同。

因此，Effective Rules 不应被理解为预先生成的一份静态规则文档，而应被理解为：

> Policy Runtime 根据当前任务上下文实时生成的、仅对本次任务或当前执行阶段生效的规则结果。

这意味着 Policy Runtime 必须进入 Agent 执行流程，成为 Agent Harness 的一部分。它不应依赖用户手动生成、复制或维护规则，而应在任务进入 Agent 前自动完成规则生成与注入。

---

## 2. 基本结论

Policy Runtime 的自动化策略可以概括为：

```text
User Input
    ↓
Policy Wrapper / Hook
    ↓
Task Analyzer
    ↓
Task Context
    ↓
Skill Registry
    ↓
Skill Activation
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
    ↓
Render Effective Prompt / Structured Context
    ↓
Inject to Agent
    ↓
Agent Execution
    ↓
Verification
    ↓
Violation Report
    ↓
Repair Loop
    ↓
Final Output
```

核心判断如下：

1. **Effective Rules 必须根据每次输入动态生成。**
2. **Policy Runtime 应作为 Agent 前置层自动运行。**
3. **现有 Agent 通常不能直接接收 Runtime 内部对象，因此需要 Adapter。**
4. **Codex 可通过 `AGENTS.md`、Skills 或 CLI Wrapper 接入。**
5. **Claude Code 可通过 `CLAUDE.md`、Hooks、Slash Commands 或 CLI Wrapper 接入。**
6. **生成结果应同时支持运行时上下文与落盘状态。**
7. **验证与修复应成为自动化闭环的一部分，而不是人工附加步骤。**

---

## 3. 核心概念

### 3.1 Policy Runtime

Policy Runtime 是 Skill / Policy 系统的执行核心。它负责根据当前任务自动完成 Skill 匹配、规则激活、冲突裁决、规则压缩和 Effective Rules 生成。

它不是 LLM 本身，也不替代 Codex 或 Claude Code，而是位于 Agent 外部的策略运行层。

### 3.2 Effective Rules

Effective Rules 是 Policy Runtime 的最终核心输出，表示当前任务上下文中真正生效的规则集合。

它通常包含：

```yaml
effective_rules:
  hard:
    - avoid undefined behavior
    - do not use banned APIs

  soft:
    - prefer RAII
    - keep functions small

  preference:
    - safety > performance by default
    - performance > readability in hot path

  exceptions:
    - hot_path:
        - raw pointers allowed with justification
```

Agent 不需要读取全部 Skills，也不需要理解 Registry、冲突图或 Reduction 过程。Agent 只需要看到当前任务的 Effective Rules。

### 3.3 Task Context

Task Context 是从用户输入、项目环境、文件类型和执行阶段中提取出的结构化任务描述。

例如用户输入：

```text
帮我写一个 C++20 低延迟队列
```

Task Analyzer 可生成：

```json
{
  "domain": "cpp",
  "task_type": "write_code",
  "context": {
    "standard": 20,
    "performance_critical": true,
    "scenario": "low_latency"
  }
}
```

Policy Runtime 后续所有 Skill 激活和规则生成都应基于 Task Context，而不是直接基于原始自然语言。

### 3.4 Adapter

Adapter 是 Policy Runtime 与现有 Coding Agent 之间的接入层。

不同 Agent 的可扩展点不同，因此需要不同 Adapter：

```text
adapters/
├── codex/
│   ├── agents_md.py
│   ├── skills_exporter.py
│   └── wrapper.py
└── claude_code/
    ├── claude_md.py
    ├── hooks.py
    ├── slash_commands.py
    └── wrapper.py
```

Adapter 的职责不是重新实现 Policy Runtime，而是将 Effective Rules 转换为目标 Agent 可读取、可执行或可感知的形式。

---

## 4. 总体自动化流程

完整的自动化链路应如下：

```text
User Input
    ↓
Policy Entry Point
    ↓
Task Analyzer
    ↓
Task Context
    ↓
Skill Registry
    ↓
Skill Activation
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
    ↓
Renderer
    ↓
Agent Adapter
    ↓
Codex / Claude Code / Custom Agent
    ↓
Verification
    ↓
Repair Loop
```

其中：

- **Policy Entry Point** 可以是 CLI Wrapper、IDE 插件、Hook 或 Agent 前置脚本。
- **Task Analyzer** 负责将自然语言任务转换为结构化 Task Context。
- **Skill Registry** 负责管理所有可用 Skills。
- **Skill Activation** 负责选择当前任务需要启用的 Skills。
- **Conflict Resolution** 负责处理规则冲突。
- **Rule Reduction** 负责压缩和裁剪规则。
- **Renderer** 负责把 Effective Rules 渲染成 Markdown、YAML、JSON 或 Agent Prompt。
- **Agent Adapter** 负责将规则注入 Codex、Claude Code 或其他 Agent。
- **Verification** 负责验证 Agent 输出是否违反 HARD 规则。
- **Repair Loop** 负责将违规结果反馈给 Agent 进行修复。

---

## 5. Effective Rules 的生成时机

Effective Rules 至少存在四类生成时机。

### 5.1 用户提交任务时生成

这是最基础、最重要的触发点。

```text
User Prompt
    ↓
Task Analyzer
    ↓
Effective Rules
    ↓
Agent
```

不同输入会产生不同规则。

例如输入：

```text
帮我写一个 C++20 低延迟队列
```

可能生成：

```yaml
effective_rules:
  hard:
    - avoid undefined behavior
    - explicit ownership required

  soft:
    - prefer RAII
    - avoid unnecessary allocation

  preference:
    - performance > readability in hot path
```

而输入：

```text
帮我设计一个 Qt QML 登录界面
```

可能生成：

```yaml
effective_rules:
  hard:
    - avoid blocking UI thread
    - keep UI state consistent

  soft:
    - reduce visual noise
    - prefer simple layout

  preference:
    - usability > visual complexity
```

### 5.2 Agent 启动前生成

这是接入 Codex / Claude Code 的最现实位置。

```text
Before Agent Run
    ↓
policy-runtime resolve
    ↓
Effective Rules
    ↓
Inject to Agent Context
    ↓
Start Agent
```

Policy Runtime 应作为 Agent 的前置步骤运行。

### 5.3 子任务切换时重新生成

复杂任务通常会被 Agent 分解为多个子任务：

```text
实现功能
    ↓
写代码
    ↓
写测试
    ↓
修改构建脚本
    ↓
更新文档
```

不同子任务需要不同规则：

```text
write_code       → C++ safety rules
write_tests      → testing rules
modify_cmake     → build-system rules
write_docs       → documentation rules
```

因此，Policy Runtime 可以在子任务级别重新生成 Step-level Effective Rules。

### 5.4 文件或工具调用前后重新校正

当 Agent 准备修改不同类型文件时，规则也应调整。

示例：

```text
BeforeEdit *.cpp
    → activate C++ rules

BeforeEdit CMakeLists.txt
    → activate CMake rules

BeforeEdit README.md
    → activate documentation rules
```

这适合通过 Hook、IDE 插件或 Agent Tool Wrapper 实现。

---

## 6. Effective Rules 的生命周期

Effective Rules 至少应支持三种生命周期。

### 6.1 Task-level Effective Rules

每个用户任务生成一次。

推荐路径：

```text
.policy/tasks/<task_id>/effective-rules.yaml
.policy/tasks/<task_id>/effective-prompt.md
.policy/tasks/<task_id>/task-context.json
.policy/tasks/<task_id>/trace.json
```

适合任务复现、审计和调试。

### 6.2 Step-level Effective Rules

Agent 在执行子任务时生成。

推荐路径：

```text
.policy/tasks/<task_id>/steps/<step_id>/effective-rules.yaml
.policy/tasks/<task_id>/steps/<step_id>/effective-prompt.md
```

适合复杂 Agent 工作流。

### 6.3 File-level Effective Rules

根据目标文件类型生成或附加。

示例：

```text
src/main.cpp        → cpp rules
CMakeLists.txt      → cmake rules
README.md           → documentation rules
package.json        → node package rules
```

适合 IDE 场景、代码编辑 Hook 和文件级验证。

---

## 7. 生成结果的存放位置

Policy Runtime 的生成结果既可以只存在于运行时内存，也可以落盘。

### 7.1 运行时上下文

对于自研 Agent Framework，最干净的方式是直接通过结构化上下文传入：

```python
effective_rules = policy_runtime.resolve(task)
agent.run(task=task, rules=effective_rules)
```

这种方式不依赖文件系统，适合完全可控的 Agent Runtime。

### 7.2 `.policy/current/` 临时状态目录

对于 Codex、Claude Code 等现有工具，推荐生成临时状态文件：

```text
.policy/current/
├── task-context.json
├── effective-rules.yaml
├── effective-prompt.md
├── trace.json
└── violations.json
```

其中：

- `task-context.json` 保存 Task Analyzer 输出。
- `effective-rules.yaml` 保存结构化 Effective Rules。
- `effective-prompt.md` 保存面向 Agent 的可读规则。
- `trace.json` 保存 Skill 激活、冲突裁决和 Reduction 路径。
- `violations.json` 保存验证结果。

### 7.3 Agent 约定文件中的自动生成区块

对 Codex / Claude Code，可将 Effective Prompt 注入它们会读取的项目说明文件中。

例如 `AGENTS.md` 或 `CLAUDE.md`：

```md
# Project Rules

这里是人工维护的长期规则。

<!-- POLICY_RUNTIME_BEGIN -->
# Effective Rules for Current Task

## HARD
- Avoid undefined behavior.

## SOFT
- Prefer RAII.
<!-- POLICY_RUNTIME_END -->
```

Policy Runtime 每次只更新自动生成区块，不覆盖人工维护部分。

---

## 8. 如何将 Effective Rules 提供给 Agent

主要有三种方式。

### 8.1 Prompt 注入

将 `effective-prompt.md` 拼接到 Agent 的 system / developer / context prompt 中。

形式如下：

```text
You must follow the following Effective Rules:

<effective-prompt.md>

User Task:
<original user task>
```

这是最直接的方式，适合自研 Agent 或 CLI Wrapper。

### 8.2 项目规则文件注入

将 Effective Rules 注入到 Agent 默认会读取的项目规则文件中。

示例：

```text
policy-runtime resolve
    ↓
update AGENTS.md / CLAUDE.md generated block
    ↓
start Codex / Claude Code
```

这种方式适合现有 Coding Agent。

### 8.3 结构化上下文传递

如果 Agent Runtime 支持结构化参数，则可以直接传递 JSON / YAML：

```json
{
  "task": "implement a low-latency queue in C++20",
  "effective_rules": {
    "hard": ["avoid undefined behavior"],
    "soft": ["prefer RAII"],
    "preference": ["performance > readability in hot path"]
  }
}
```

这是长期更优的方式，但依赖 Agent Runtime 的开放程度。

---

## 9. Codex 接入策略

Codex 的现实接入方式应以外部适配为主，不假设能够修改 Codex 内核。

### 9.1 `AGENTS.md` 注入

Policy Runtime 可在每次任务执行前生成 Effective Prompt，并写入 `AGENTS.md` 的自动生成区块。

流程：

```text
policy resolve <task>
    ↓
render effective-prompt.md
    ↓
inject AGENTS.md
    ↓
codex <task>
```

建议不要直接覆盖整个 `AGENTS.md`，而是维护自动生成区块。

### 9.2 Codex Skills 导出

稳定、长期、通用的规则可以导出为 Codex Skills。

但不应将大量 Domain Skills 全部导出为 Codex Skills，因为这会导致上下文负担过重，也会削弱动态裁剪能力。

推荐策略：

```text
长期稳定能力 → Codex Skill
当前任务动态规则 → Effective Rules 注入
```

### 9.3 Codex CLI Wrapper

推荐提供封装命令：

```bash
policy-codex "帮我写一个 C++20 低延迟队列"
```

其内部等价于：

```bash
policy resolve "$TASK"
policy inject --target codex
codex "$TASK"
policy verify
```

对用户来说，整个流程仍然是一次命令。

---

## 10. Claude Code 接入策略

Claude Code 适合通过 `CLAUDE.md`、Hooks、Slash Commands 和 Wrapper 进行接入。

### 10.1 `CLAUDE.md` 注入

与 Codex 的 `AGENTS.md` 类似，Policy Runtime 可以更新 `CLAUDE.md` 的自动生成区块。

```text
policy resolve <task>
    ↓
render effective-prompt.md
    ↓
inject CLAUDE.md
    ↓
claude <task>
```

### 10.2 Hooks 接入

Claude Code 的 Hook 机制适合做执行前、执行中和执行后的自动化控制。

可以设计：

```text
PreToolUse / BeforeEdit
    → policy-runtime resolve or check-intent

PostToolUse / AfterEdit
    → policy-runtime verify-changes

Stop / SubagentStop
    → policy-runtime summarize-violations
```

Hooks 的价值在于让 Policy Runtime 不只在任务开始前运行，也能在 Agent 修改文件、调用工具或结束任务时自动介入。

### 10.3 Slash Commands

可以定义自定义命令：

```text
/policy:resolve
/policy:review
/policy:repair
/policy:explain
```

这些命令用于手动触发或调试 Policy Runtime，但最终的生产流程仍应以自动化 Wrapper / Hook 为主。

---

## 11. Wrapper 模式

Wrapper 模式是最推荐的 MVP 接入方式。

用户不直接调用 Codex / Claude Code，而是调用：

```bash
policy-codex "<task>"
policy-claude "<task>"
```

Wrapper 内部流程：

```text
1. 接收用户任务
2. 调用 policy-runtime resolve
3. 生成 .policy/current/effective-rules.yaml
4. 生成 .policy/current/effective-prompt.md
5. 注入 AGENTS.md / CLAUDE.md 或临时 prompt
6. 启动目标 Agent
7. 执行后调用 policy verify
8. 如有违规，生成 repair prompt
9. 可选择重新调用 Agent 修复
```

Wrapper 的优点：

- 不依赖修改 Agent 内核。
- 容易测试。
- 容易集成现有命令行流程。
- 可以逐步加入验证、修复和追踪。

---

## 12. Hook 模式

Hook 模式适合在 Agent 执行过程中进行动态校正。

### 12.1 执行前 Hook

用于生成或刷新 Effective Rules。

```text
BeforeAgentRun
    → resolve task-level rules
```

### 12.2 工具调用前 Hook

用于根据目标文件、工具类型或子任务类型生成更细粒度规则。

```text
BeforeEdit src/*.cpp
    → activate cpp rules

BeforeEdit CMakeLists.txt
    → activate cmake rules
```

### 12.3 工具调用后 Hook

用于验证 Agent 修改是否违反 HARD rules。

```text
AfterEdit
    → run validators
    → produce violations.json
```

### 12.4 任务结束 Hook

用于生成最终验证报告。

```text
AfterAgentStop
    → summarize applied rules
    → summarize violations
    → summarize unresolved issues
```

Hook 模式的价值在于把 Policy Runtime 从一次性前置步骤，升级为执行过程中的持续约束层。

---

## 13. State 与 Trace 管理

Policy Runtime 必须管理状态，否则无法复现规则生成过程，也无法解释为什么某条规则生效。

### 13.1 推荐状态目录

```text
.policy/
├── current/
│   ├── task-context.json
│   ├── effective-rules.yaml
│   ├── effective-prompt.md
│   ├── trace.json
│   └── violations.json
│
└── tasks/
    └── <task_id>/
        ├── task-context.json
        ├── active-skills.json
        ├── effective-rules.yaml
        ├── effective-prompt.md
        ├── trace.json
        ├── violations.json
        └── steps/
            └── <step_id>/
                ├── task-context.json
                ├── effective-rules.yaml
                └── violations.json
```

### 13.2 Trace 内容

`trace.json` 应至少记录：

```json
{
  "task_id": "...",
  "task_context": {},
  "matched_skills": [],
  "activated_skills": [],
  "excluded_skills": [],
  "conflicts": [],
  "resolution_decisions": [],
  "reduction_steps": [],
  "effective_rules_hash": "..."
}
```

Trace 的作用：

- 解释规则来源。
- 复现 Agent 行为。
- 调试 Skill 激活问题。
- 支持审计与版本回滚。

---

## 14. Verification 与 Repair Loop

Policy Runtime 的职责不应止于规则注入。规则是否被遵守，必须通过验证机制检查。

### 14.1 Verification

Verification 根据 Effective Rules 中的 HARD rules 执行检查。

示例：

```text
HARD: do not use banned APIs
    → grep / AST checker / clang-tidy

HARD: avoid undefined behavior
    → clang-tidy / sanitizer / custom checker

HARD: avoid blocking UI thread
    → static check / code review evaluator
```

验证输出：

```json
{
  "violations": [
    {
      "rule": "do not use banned APIs",
      "file": "src/main.cpp",
      "line": 42,
      "severity": "error",
      "message": "strcpy is not allowed"
    }
  ]
}
```

### 14.2 Repair Loop

如果发现违规，Policy Runtime 应生成修复上下文：

```md
# Policy Violation Report

The generated code violates the following HARD rules:

- Rule: do not use banned APIs
- Location: src/main.cpp:42
- Detail: strcpy is not allowed

Please repair the code without violating the Effective Rules.
```

然后将该报告反馈给 Agent。

完整流程：

```text
Agent Execution
    ↓
Verification
    ↓
Violation Report
    ↓
Repair Prompt
    ↓
Agent Repair
    ↓
Re-verify
```

这使 Policy Runtime 从“规则提示器”升级为“规则闭环执行层”。

---

## 15. 推荐 CLI 设计

### 15.1 `policy resolve`

根据任务生成 Effective Rules。

```bash
policy resolve "帮我写一个 C++20 低延迟队列"
```

输出：

```text
.policy/current/task-context.json
.policy/current/effective-rules.yaml
.policy/current/effective-prompt.md
.policy/current/trace.json
```

### 15.2 `policy inject`

将 Effective Prompt 注入目标 Agent。

```bash
policy inject --target codex
policy inject --target claude
```

支持目标：

```text
codex        → AGENTS.md
claude       → CLAUDE.md
custom       → stdout / prompt file
```

### 15.3 `policy verify`

根据当前 Effective Rules 验证 Agent 输出。

```bash
policy verify
```

输出：

```text
.policy/current/violations.json
```

### 15.4 `policy run`

完整运行一次任务。

```bash
policy run --agent codex "帮我写一个 C++20 低延迟队列"
```

内部流程：

```text
resolve → inject → agent run → verify → optional repair
```

### 15.5 Agent 专用包装命令

```bash
policy-codex "<task>"
policy-claude "<task>"
```

它们是 `policy run --agent ...` 的快捷入口。

---

## 16. 推荐项目结构

```text
ai_policy_runtime/
├── core/
│   ├── task_analyzer/
│   │   ├── extractor.py
│   │   ├── llm_extractor.py
│   │   └── schema.py
│   │
│   ├── registry/
│   │   ├── registry.py
│   │   ├── loader.py
│   │   ├── metadata.py
│   │   └── lifecycle.py
│   │
│   ├── activation/
│   │   ├── matcher.py
│   │   ├── context.py
│   │   ├── trigger.py
│   │   └── dependency.py
│   │
│   ├── conflicts/
│   │   ├── normalizer.py
│   │   ├── classifier.py
│   │   ├── resolver.py
│   │   └── policies.py
│   │
│   ├── reduction/
│   │   ├── reducer.py
│   │   ├── override.py
│   │   ├── deduplicate.py
│   │   └── exceptions.py
│   │
│   ├── renderer/
│   │   ├── markdown_renderer.py
│   │   ├── yaml_renderer.py
│   │   └── prompt_renderer.py
│   │
│   └── effective_rules/
│       ├── model.py
│       └── builder.py
│
├── skills/
│   ├── platform/
│   ├── domain/
│   │   ├── cpp/
│   │   ├── rust/
│   │   ├── ui_design/
│   │   └── documentation/
│   ├── generic/
│   └── user/
│
├── adapters/
│   ├── codex/
│   │   ├── inject_agents_md.py
│   │   ├── skills_exporter.py
│   │   └── wrapper.py
│   │
│   └── claude_code/
│       ├── inject_claude_md.py
│       ├── hooks.py
│       ├── slash_commands.py
│       └── wrapper.py
│
├── state/
│   ├── task_store.py
│   ├── rule_cache.py
│   └── trace_store.py
│
├── docs/reference/verification/
│   ├── validators/
│   │   ├── clang_tidy.py
│   │   ├── regex_checker.py
│   │   ├── ast_checker.py
│   │   └── llm_evaluator.py
│   └── violation_report.py
│
├── repair/
│   ├── critique.py
│   ├── repair_prompt.py
│   └── retry.py
│
├── cli/
│   ├── resolve.py
│   ├── inject.py
│   ├── verify.py
│   └── run.py
│
├── tests/
│
└── .policy/
    └── current/
        ├── task-context.json
        ├── effective-rules.yaml
        ├── effective-prompt.md
        ├── trace.json
        └── violations.json
```

该结构明确区分：

- Core：策略运行时核心。
- Skills：规则库。
- Adapters：面向不同 Agent 的接入层。
- State：任务状态与追踪。
- Verification：验证层。
- Repair：修复闭环。
- CLI：用户入口。

---

## 17. 典型执行场景

### 17.1 C++ 代码生成任务

用户输入：

```text
帮我写一个 C++20 低延迟队列
```

流程：

```text
Task Analyzer
    → domain=cpp
    → standard=20
    → performance_critical=true

Skill Activation
    → cpp.base
    → cpp.safety.lifetime
    → cpp.safety.ownership
    → cpp.performance.hot_path
    → project.low_latency

Rule Reduction
    → hard: avoid UB, explicit ownership
    → soft: prefer RAII, avoid unnecessary allocation
    → preference: performance > readability in hot path

Injection
    → AGENTS.md / CLAUDE.md / prompt context
```

### 17.2 UI 设计任务

用户输入：

```text
帮我优化一个登录界面，不要太复杂
```

流程：

```text
Task Analyzer
    → domain=ui_design
    → task_type=design_review
    → context.simplicity_required=true

Skill Activation
    → ui.layout_hierarchy
    → ui.visual_noise_reduction
    → ui.action_path
    → ui.form_design

Effective Rules
    → reduce visual noise
    → avoid duplicate primary actions
    → keep one clear action path
    → usability > decoration
```

### 17.3 文档生成任务

用户输入：

```text
生成一份正式 Markdown 文档，语言准确，不要 AI 风格
```

流程：

```text
Task Analyzer
    → domain=documentation
    → task_type=write_document
    → context.formal_style=true

Skill Activation
    → docs.structure
    → docs.formal_style
    → docs.no_process_log
    → docs.completeness

Effective Rules
    → use formal language
    → present final system only
    → avoid discussion record
    → preserve completeness and logical continuity
```

---

## 18. 最小可落地版本

MVP 不需要实现完整 Hook、Step-level Rules 或复杂验证。

最小版本只需要：

```text
policy resolve
policy inject
policy run
```

### 18.1 MVP 流程

```text
User Task
    ↓
policy run --agent codex <task>
    ↓
Task Analyzer
    ↓
Effective Rules
    ↓
Inject AGENTS.md
    ↓
Run Codex
```

### 18.2 MVP 文件

```text
.policy/current/
├── task-context.json
├── effective-rules.yaml
├── effective-prompt.md
└── trace.json
```

### 18.3 MVP 能力

- 任务级规则生成。
- Codex / Claude Code 规则注入。
- 自动生成区块维护。
- 基础 trace。
- 手动或半自动 verification。

MVP 的目标不是一次实现完整闭环，而是验证：

> 当前任务输入能否自动生成更准确的 Agent 规则上下文。

---

## 19. 进阶版本

在 MVP 成立后，可逐步升级。

### 19.1 Step-level Policy

Agent 分解任务后，每个子任务重新生成 Effective Rules。

```text
Subtask
    ↓
Resolve Step-level Effective Rules
    ↓
Inject / Apply
```

### 19.2 File-level Policy

根据文件类型或修改位置生成规则。

```text
BeforeEdit *.cpp
    → cpp rules

BeforeEdit *.qml
    → qml rules

BeforeEdit CMakeLists.txt
    → cmake rules
```

### 19.3 Verification Gate

HARD rules 不只是提示，而是 gate。

```text
Agent Output
    ↓
Policy Verify
    ↓
Pass → Final
Fail → Repair
```

### 19.4 Auto Repair

违规后自动生成修复任务。

```text
Violation Report
    ↓
Repair Prompt
    ↓
Agent Repair
    ↓
Re-verify
```

### 19.5 Policy Trace UI

为每次任务展示：

- 激活了哪些 Skills。
- 排除了哪些 Skills。
- 哪些规则发生冲突。
- 冲突如何裁决。
- Effective Rules 如何生成。
- Agent 是否违反规则。

---

## 20. 设计原则

### 20.1 不让 Agent 读取全部 Skills

Agent 应只读取当前任务的 Effective Rules。

全部 Skills 由 Registry 管理，不能直接暴露给 Agent，否则会造成上下文膨胀、规则冲突和行为不稳定。

### 20.2 不将 Effective Rules 静态化

Effective Rules 是动态产物，不应长期固定。

它应随输入、文件、子任务和项目上下文变化。

### 20.3 不覆盖人工维护规则

注入 `AGENTS.md` / `CLAUDE.md` 时，应使用自动生成区块，避免覆盖人工规则。

### 20.4 保留 Trace

每次规则生成都应可追踪、可解释、可复现。

### 20.5 先注入，再验证，最后闭环

合理演进顺序是：

```text
规则注入
    ↓
结果验证
    ↓
自动修复
```

不应在 MVP 阶段同时实现所有能力。

---

## 21. 常见错误做法

### 21.1 预先生成一份全局规则文件长期使用

错误原因：不同任务所需规则不同，静态规则会过宽、过杂，最终降低 Agent 行为稳定性。

### 21.2 将整个 Domain Skills 注入 Agent

错误原因：Domain 是 Skill Library，不是一个大 Skill。应从 Domain Library 中检索、激活、裁剪当前任务需要的 Skill 子集。

### 21.3 让 LLM 自己理解所有 Skills 并决定使用哪些

错误原因：Skill 激活、冲突裁决和 Rule Reduction 应尽量由确定性 Runtime 完成，而不是交给 LLM 猜测。

### 21.4 每次覆盖整个 `AGENTS.md` / `CLAUDE.md`

错误原因：会破坏项目长期规则和人工维护内容。应只更新自动生成区块。

### 21.5 只注入规则，不验证结果

错误原因：规则如果不能验证，只是提示。HARD rules 应逐步接入验证器，形成 gate。

### 21.6 没有状态和 Trace

错误原因：无法解释为什么某条规则生效，也无法复现 Agent 行为。

---

## 22. 最终结论

Policy Runtime 的正确位置不是一个离线规则生成工具，而是 Agent Harness 的自动化策略层。

它应在每次任务执行前，根据当前输入动态生成 Effective Rules；在执行过程中，根据子任务、文件和工具调用重新校正规则；在执行后，根据 Effective Rules 验证输出，并在必要时驱动修复闭环。

最终自动化链路应为：

```text
policy-codex "<task>"
或
policy-claude "<task>"

    ↓

Task Analysis
    ↓
Skill Activation
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
    ↓
Agent Injection
    ↓
Agent Execution
    ↓
Verification
    ↓
Repair Loop
```

一句话概括：

> Effective Rules 必须按任务动态生成；Policy Runtime 必须自动运行；Agent 只消费当前任务的最终规则，而不直接面对完整 Skill 系统。
