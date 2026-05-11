# Skill DSL 与 Policy Runtime 设计文档

## 摘要

本文档定义一套面向 AI 系统的通用 Skill / Policy Runtime 框架。该框架的目标不是编写更多提示词，而是将 Skills 从自然语言提示升级为可注册、可调度、可仲裁、可裁剪、可验证的策略与约束单元。

在该体系中，Skill 不再是简单的 Prompt 片段，而是带有作用域、触发条件、规则类型、优先级、异常条件和生命周期的规则模块。Policy Runtime 根据当前任务上下文自动激活相关 Skills，经过规则标准化、冲突检测、规则裁决与规则压缩，最终生成当前任务唯一有效的 Effective Rules，并将其提供给 LLM、Agent Runtime、工具链或验证系统使用。

该体系的核心思想是：自然语言用于表达意图，结构化 DSL 用于组织规则，Rule IR 用于系统处理，Effective Rules 用于驱动 AI 受约束地生成结果。

---

## 目录

1. 问题背景
2. 基本概念
3. Skills 的本质
4. 设计目标
5. 总体架构
6. Skill DSL 设计
7. Rule IR：规则中间表示
8. Skill Registry 设计
9. Task Analyzer：任务上下文提取
10. Skill Activation：技能激活机制
11. Conflict Resolution：冲突检测与裁决
12. Rule Reduction：规则压缩机制
13. Effective Rules：最终输出
14. AI 使用 Effective Rules 的方式
15. 大规模 Domain Skills 管理
16. Verification 与 Repair Loop
17. 推荐项目结构
18. 最小实现模块说明
19. 工程落地路径
20. 设计边界与不完备性
21. 结论

---

## 1. 问题背景

现有 AI 系统中的 Skills、System Prompt、Guidelines、Playbooks、Tool Instructions 等机制，主要用于约束模型行为、缩小输出空间、提高结果稳定性与精确性。

这类机制在形式上通常表现为自然语言描述，例如：

```text
当用户请求生成 C++ 代码时，应遵守 C++ Core Guidelines，避免未定义行为，优先使用 RAII，除非用户明确要求底层性能优化。
```

这类描述本质上已经包含逻辑结构：

```text
IF task = generate_cpp_code
THEN follow_cpp_core_guidelines
AND avoid_undefined_behavior
AND prefer_raii
UNLESS low_level_performance_required
```

问题在于，自然语言本身缺乏稳定的结构，不利于机器解析、规则组合、冲突检测、优先级裁决和自动验证。当 Skills 数量较少时，直接写入 Prompt 尚可工作；当 Skills 数量增加，尤其是进入企业级、多领域、多项目、多 Agent 场景时，简单拼接 Prompt 会导致规则冲突、上下文污染、行为不可预测和维护困难。

因此，需要一套通用的 Skill / Policy Runtime 框架，将 Skills 从自然语言提示升级为可管理的系统资产。

---

## 2. 基本概念

### 2.1 Skill

Skill 是一个带有作用域、规则、优先级和上下文条件的规则模块。它不是单纯的文本片段，而是一个可注册、可匹配、可组合、可裁剪的策略单元。

### 2.2 Skill DSL

Skill DSL 是人类编写 Skill 的半结构化语言。它介于自然语言与形式逻辑之间：

- 保留自然语言的可读性；
- 引入结构化字段，便于系统解析；
- 支持规则类型、触发条件、优先级、异常条件等工程属性。

### 2.3 Rule IR

Rule IR 是 Runtime 内部使用的规则中间表示。Skill DSL 面向人类，Rule IR 面向系统。Runtime 不应直接依赖自然语言进行冲突检测，而应先将 DSL 编译为规范化规则对象。

### 2.4 Policy Runtime

Policy Runtime 是执行 Skill 管理、任务匹配、规则激活、冲突裁决和规则压缩的系统。它的职责是根据当前任务生成 Effective Rules，而不是让 LLM 自己理解全部 Skills。

### 2.5 Effective Rules

Effective Rules 是当前任务上下文下真正生效的规则集合。它是 Policy Runtime 的最终输出，也是提供给 LLM、Agent Runtime、工具链和验证系统的核心输入。

---

## 3. Skills 的本质

Skills 的本质是：

> 用自然语言或半结构化语言描述的行为约束逻辑。

它们的目的包括：

- 限制 AI 的行为边界；
- 降低输出不确定性；
- 固化决策偏好；
- 提高结果一致性；
- 将领域知识注入 AI 工作流；
- 将可验证规则转化为工程控制点。

从逻辑角度看，Skill 中常见的表达可以转化为如下结构：

```text
WHEN condition
MUST action
SHOULD preference
UNLESS exception
```

例如：

```text
当生成 C++ 代码时，必须避免未定义行为，应优先使用 RAII，除非当前代码位于性能关键路径。
```

可以抽象为：

```text
(task = generate_cpp_code) -> MUST avoid_undefined_behavior
(task = generate_cpp_code) -> SHOULD prefer_raii
(task = hot_path) -> ALLOW lower_level_control WITH justification
```

因此，Skills 确实是在描述逻辑，只是原始形态多为自然语言。真正的工程问题不在于“是否使用逻辑”，而在于如何把自然语言规则转化为系统可以处理的结构化规则。

---

## 4. 设计目标

一套可工程化的 Skill / Policy Runtime 框架应满足以下目标。

### 4.1 人类可读

Skill 需要由人类维护，因此不能直接要求所有作者编写形式逻辑或低层 IR。DSL 应保留足够的自然语言表达能力。

### 4.2 机器可解析

Skill 必须具备稳定结构，否则无法进行自动激活、规则分类、冲突检测和规则压缩。

### 4.3 可组合

多个 Skills 可以被组合使用，但不能简单拼接。系统需要支持依赖、覆盖、继承、分层和裁剪。

### 4.4 可冲突检测

多个 Skills 必然会产生冲突。冲突应作为一等公民被建模，而不是交给 LLM 自行解释。

### 4.5 可裁剪

最终提供给 AI 的规则应是当前任务需要的最小有效规则集，而不是所有相关 Skills 的堆叠。

### 4.6 可验证

部分规则应能够映射到静态分析、AST 检查、Lint、测试、Sanitizer 或其他验证机制。

### 4.7 可扩展

框架应支持从最小实现逐步扩展到企业级 Policy Runtime、Agent Runtime、CI Gate 和 AI IDE 集成。

---

## 5. 总体架构

完整系统流程如下：

```text
User Task
    ↓
Task Analyzer
    ↓
Task Context
    ↓
Skill Registry
    ↓
Skill Activation
    ↓
Rule Extraction
    ↓
Rule Normalization
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
    ↓
LLM / Agent Runtime / Tools
    ↓
Verification
    ↓
Repair Loop
    ↓
Final Output
```

核心原则是：

> LLM 不应直接面对全部 Skills。Policy Runtime 应先根据任务上下文生成 Effective Rules，LLM 只接收当前任务已经裁剪好的有效规则。

---

## 6. Skill DSL 设计

### 6.1 基本结构

Skill DSL 推荐采用 YAML、JSON 或其他半结构化格式。示例：

```yaml
skill_id: cpp.safety.lifetime
version: 1.0.0
name: C++ Lifetime Safety
level: DOMAIN
priority: 90

scope:
  domains:
    - cpp
  triggers:
    - write_code
    - refactor_code
    - review_code

context:
  language: cpp
  standard: ">=17"

rules:
  hard:
    - id: cpp.lifetime.no_dangling_reference
      target: lifetime
      action: FORBID
      value: dangling_reference
      description: Do not produce dangling references.

  soft:
    - id: cpp.lifetime.prefer_value_or_raii
      target: lifetime
      action: PREFER
      value: value_semantics_or_raii
      description: Prefer value semantics or RAII-managed ownership.

  preference:
    - id: cpp.lifetime.clarity_over_micro_optimization
      target: implementation_style
      action: PREFER_ORDER
      value: clarity > micro_optimization

exceptions:
  - when: hot_path == true
    allow:
      - explicit_low_level_lifetime_control
    require:
      - justification
```

### 6.2 规则类型

Skill DSL 应明确区分三类规则。

#### HARD

HARD 表示强约束。此类规则原则上应可验证或可近似验证。违反 HARD 规则意味着结果不能被接受。

示例：

```yaml
hard:
  - Do not use banned APIs.
  - Avoid undefined behavior.
  - Ensure ownership is explicit.
```

#### SOFT

SOFT 表示工程准则或默认建议。它们可以被更高优先级规则、上下文条件或异常条件覆盖。

示例：

```yaml
soft:
  - Prefer RAII.
  - Avoid raw pointers.
  - Keep functions small.
```

#### PREFERENCE

PREFERENCE 表示决策偏好，主要用于多方案排序或冲突裁决。

示例：

```yaml
preference:
  - safety > performance
  - readability > cleverness
  - standard_library > custom_utility
```

### 6.3 作用域

Skill 必须声明作用域。常见字段包括：

- domain；
- trigger；
- context；
- capability；
- tags；
- project；
- language；
- framework；
- file type。

作用域用于判断 Skill 是否应被当前任务激活。

### 6.4 优先级

Skill 应具备两个层面的优先级：

1. level：用于跨层级覆盖；
2. priority：用于同层级排序。

推荐层级：

```text
PLATFORM > DOMAIN > PROJECT > TASK
```

其中：

- PLATFORM：平台安全规则，通常不可覆盖；
- DOMAIN：领域规则，如 C++、Rust、Python、UI Design；
- PROJECT：项目规则，如某个代码库、产品、团队规范；
- TASK：当前任务临时规则。

### 6.5 异常条件

异常条件是成熟 Skill 系统不可缺少的部分。没有异常条件的规则系统容易僵化，也容易被绕过。

示例：

```yaml
exceptions:
  - when: performance_critical == true
    allow:
      - raw_pointer
    require:
      - justification
      - ownership_comment
```

---

## 7. Rule IR：规则中间表示

### 7.1 为什么需要 Rule IR

Skill DSL 面向人类，因此允许一定程度的自然语言描述。Runtime 不能直接依赖自然语言做冲突检测和规则裁剪，而应将 DSL 编译为规范化 Rule IR。

### 7.2 Rule IR 基本模型

最小可用 Rule IR：

```json
{
  "id": "cpp.raw_pointer.avoid",
  "strength": "SOFT",
  "target": "raw_pointer",
  "action": "FORBID",
  "value": "raw_pointer",
  "condition": null,
  "source": "cpp.safety.ownership",
  "level": "DOMAIN",
  "priority": 80
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| id | 规则唯一标识 |
| strength | HARD / SOFT / PREFERENCE |
| target | 规则作用对象 |
| action | REQUIRE / FORBID / ALLOW / PREFER / PREFER_ORDER |
| value | 规则值 |
| condition | 生效条件 |
| source | 来源 Skill |
| level | Skill 层级 |
| priority | Skill 优先级 |

### 7.3 DSL 到 IR 的示例

DSL：

```yaml
- avoid raw pointers
```

IR：

```json
{
  "strength": "SOFT",
  "target": "raw_pointer",
  "action": "FORBID",
  "value": "raw_pointer",
  "condition": null
}
```

DSL：

```yaml
- allow raw pointers in hot path with justification
```

IR：

```json
{
  "strength": "SOFT",
  "target": "raw_pointer",
  "action": "ALLOW",
  "value": "raw_pointer",
  "condition": "hot_path == true",
  "requires": ["justification"]
}
```

---

## 8. Skill Registry 设计

### 8.1 定义

Skill Registry 是 Skills 的注册中心和决策入口。它负责记录有哪些 Skills、它们的元数据、版本、生命周期、依赖关系、冲突关系和可用状态。

### 8.2 Registry 不应做的事

Skill Registry 不应直接让 LLM 读取全部 Skills，也不应简单拼接 Skills。它只负责管理 Skills，并为后续 Activation、Conflict Resolution 和 Reduction 提供输入。

### 8.3 Skill Descriptor

示例：

```yaml
skill_id: cpp.safety.ownership
version: 1.0.0
name: C++ Ownership Safety
description: Rules for explicit and safe ownership in C++.

level: DOMAIN
priority: 85
status: stable

domains:
  - cpp

categories:
  - safety
  - ownership

tags:
  - ownership
  - lifetime
  - resource-management

capabilities:
  - code_generation
  - code_review
  - refactor

triggers:
  - write_code
  - review_code
  - refactor_code

context:
  language: cpp
  standard: ">=17"

dependencies:
  - cpp.base.language

incompatibilities: []

author: core-team
```

### 8.4 生命周期

Skill 应支持生命周期管理：

```text
draft → experimental → stable → deprecated → removed
```

生产环境中应优先使用 stable Skill；experimental Skill 可用于测试或特定项目；deprecated Skill 应提示迁移路径。

---

## 9. Task Analyzer：任务上下文提取

### 9.1 任务

Task Analyzer 的职责是将用户自然语言请求转化为结构化 Task Context。

用户请求：

```text
为低延迟撮合引擎写一段 C++20 代码。
```

Task Context：

```json
{
  "domain": "cpp",
  "task_type": "write_code",
  "context": {
    "language": "cpp",
    "standard": 20,
    "performance_critical": true,
    "scenario": "matching_engine"
  },
  "capabilities": ["code_generation"],
  "tags": ["low_latency", "hot_path", "systems_programming"]
}
```

### 9.2 是否需要 LLM

Task Analyzer 可以有三种实现方式：

| 方式 | 是否需要 LLM | 适用场景 |
|---|---|---|
| 规则 / 正则 / 关键词 | 否 | 简单、可控、低成本 |
| LLM 分类器 / 抽取器 | 是 | 自然语言复杂、上下文较多 |
| 混合模式 | 可选 | 推荐方案 |

推荐采用混合模式：

```text
User Request
    ↓
Deterministic Extractor
    ↓
置信度足够 → Task Context
    ↓
置信度不足 → LLM Extractor
    ↓
Task Context
```

### 9.3 原则

LLM 可用于将模糊自然语言转化为结构化 Task Context，但后续 Skill Activation、Conflict Resolution、Rule Reduction 应尽量由确定性 Runtime 完成。

---

## 10. Skill Activation：技能激活机制

### 10.1 激活流程

Skill Activation 根据 Task Context 从 Registry 中选择当前任务需要的 Skills。

```text
Task Context
    ↓
Domain Match
    ↓
Trigger Match
    ↓
Capability Match
    ↓
Context Match
    ↓
Dependency Check
    ↓
Active Skills
```

### 10.2 匹配维度

常见匹配维度包括：

- domain；
- trigger；
- capability；
- tags；
- context；
- project；
- file type；
- framework；
- language version。

### 10.3 示例

任务：

```text
为低延迟撮合引擎写一段 C++20 代码。
```

可能激活：

```text
cpp.base.language
cpp.safety.undefined_behavior
cpp.safety.lifetime
cpp.safety.ownership
cpp.performance.hot_path
cpp.performance.allocation
project.low_latency
```

不应激活：

```text
cpp.gui.qt
cpp.documentation.api_reference
rust.backend.axum
python.data_science
```

---

## 11. Conflict Resolution：冲突检测与裁决

### 11.1 为什么必须做冲突检测

多个 Skills 同时激活时，规则冲突不可避免。例如：

```text
SHOULD avoid raw pointers
ALLOW raw pointers in hot path
```

如果直接交给 LLM 判断，会导致行为不稳定。Runtime 应先进行冲突检测与裁决。

### 11.2 规则规范化

冲突检测的前提是将规则转化为统一结构：

```text
(strength, target, action, value, condition)
```

示例：

| 原始规则 | 规范化结果 |
|---|---|
| avoid raw pointers | SOFT, raw_pointer, FORBID, raw_pointer, null |
| allow raw pointers in hot path | SOFT, raw_pointer, ALLOW, raw_pointer, hot_path |
| must not use strcpy | HARD, api_usage, FORBID, strcpy, null |

### 11.3 冲突类型

#### HARD × HARD

两个强规则互相矛盾，必须失败。

```text
MUST use X
MUST NOT use X
```

处理方式：构建失败或要求人工裁决。

#### HARD × SOFT

HARD 压制 SOFT。

```text
MUST NOT use raw pointers
SHOULD use raw pointers for performance
```

处理方式：保留 HARD，裁剪 SOFT。

#### SOFT × SOFT

可以通过层级、优先级、上下文条件和异常条件裁决。

```text
SHOULD avoid raw pointers
ALLOW raw pointers WHEN hot_path
```

处理方式：形成默认规则加条件例外。

#### PREFERENCE 冲突

偏好冲突用于方案排序，需要通过优先级、权重或上下文裁决。

```text
readability > performance
performance > readability WHEN hot_path
```

处理方式：默认偏好和条件偏好同时保留。

### 11.4 裁决原则

推荐默认裁决原则：

```text
PLATFORM > DOMAIN > PROJECT > TASK
HARD > SOFT > PREFERENCE
Same Level: higher priority wins
Condition-specific rule refines general rule
Exception does not delete default rule; it narrows it
```

---

## 12. Rule Reduction：规则压缩机制

### 12.1 定义

Rule Reduction 是将已激活、已裁决的规则压缩成最小有效规则集的过程。

它不是简单删除规则，而是将规则整理成：

```text
默认规则 + 条件例外 + 当前偏好排序
```

### 12.2 为什么需要 Reduction

如果直接把所有 Active Skills 的规则提供给 LLM，会导致：

- 上下文过长；
- 冗余规则过多；
- 规则重复；
- 规则遮蔽；
- LLM 对优先级理解不稳定。

Reduction 的目标是：

> 只保留当前任务真正需要的规则。

### 12.3 Reduction 操作

常见操作包括：

- 去重；
- 移除被覆盖规则；
- 合并相同 target 的规则；
- 将异常条件折叠到默认规则；
- 删除低优先级软规则；
- 将偏好规则整理为排序表；
- 保留可验证 HARD 规则。

### 12.4 示例

输入：

```text
SOFT: avoid raw pointers
SOFT: allow raw pointers in hot path with justification
PREFERENCE: readability > performance
PREFERENCE: performance > readability WHEN hot_path
```

输出：

```text
Default:
  avoid raw pointers
  readability > performance

When hot_path:
  allow raw pointers with justification
  performance > readability
```

---

## 13. Effective Rules：最终输出

### 13.1 定义

Effective Rules 是当前任务上下文下唯一有效的规则集合，是 Policy Runtime 的最终产物。

LLM 不应看到完整 Registry、所有 Skills、冲突历史或规则继承链。LLM 只应接收 Effective Rules。

### 13.2 示例

```yaml
effective_rules:
  hard:
    - id: cpp.ub.avoid
      description: Avoid undefined behavior.
    - id: cpp.ownership.explicit
      description: Resource ownership must be explicit.
    - id: cpp.api.no_banned
      description: Do not use banned APIs.
      values:
        - gets
        - strcpy

  soft:
    - id: cpp.raii.prefer
      description: Prefer RAII for resource management.
    - id: cpp.raw_pointer.default
      description: Avoid raw pointers by default.

  preferences:
    default:
      - safety > performance
      - readability > cleverness
    hot_path:
      - performance > readability

  exceptions:
    - when: hot_path == true
      allow:
        - raw_pointer
      require:
        - justification
        - explicit ownership explanation
```

---

## 14. AI 使用 Effective Rules 的方式

### 14.1 方式一：注入 System Prompt

最简单的方式是将 Effective Rules 转为 System Prompt 的一部分。

```text
You are a coding assistant.

Follow these effective rules:

HARD:
- Avoid undefined behavior.
- Resource ownership must be explicit.
- Do not use banned APIs: gets, strcpy.

SOFT:
- Prefer RAII.
- Avoid raw pointers by default.

PREFERENCE:
- Default: safety > performance.
- Hot path: performance > readability.

EXCEPTIONS:
- Raw pointers are allowed in hot paths only with justification and explicit ownership explanation.
```

适合：简单 Agent、现有 LLM 接口、快速集成。

### 14.2 方式二：作为结构化上下文传给 Agent Runtime

```json
{
  "task": {
    "type": "write_code",
    "language": "cpp",
    "standard": 20
  },
  "effective_rules": {
    "hard": [...],
    "soft": [...],
    "preferences": [...],
    "exceptions": [...]
  }
}
```

适合：自研 Agent Runtime、多工具调用、多阶段执行。

### 14.3 方式三：多阶段执行

Effective Rules 不仅用于生成，也用于验证和修复。

```text
Generate
    ↓
Validate HARD rules
    ↓
Evaluate SOFT rules
    ↓
Repair violations
    ↓
Revalidate
    ↓
Final Output
```

适合：AI IDE、CI Gate、自动代码修复、企业级 Agent。

---

## 15. 大规模 Domain Skills 管理

### 15.1 Domain 不应是一个大 Skill

对于 C++、Rust、前端、UI、架构设计等复杂领域，一个 Domain 内部必然包含大量 Skills。错误做法是创建一个巨大 Skill，把所有规则塞进去。

正确做法是：

> Domain 是 Skill Library，而不是单个 Skill。

### 15.2 小型化 Skill

以 C++ 为例：

```text
cpp/
├── base/
│   ├── language_basics.skill
│   ├── standard_library.skill
│   └── style_baseline.skill
│
├── safety/
│   ├── undefined_behavior.skill
│   ├── lifetime.skill
│   ├── ownership.skill
│   └── bounds_checking.skill
│
├── concurrency/
│   ├── data_race.skill
│   ├── thread_lifetime.skill
│   └── atomics.skill
│
├── performance/
│   ├── allocation.skill
│   ├── cache_locality.skill
│   └── hot_path.skill
│
└── project_types/
    ├── gui_qt.skill
    ├── low_latency.skill
    ├── library_api.skill
    └── embedded.skill
```

### 15.3 Metadata 驱动选择

Runtime 不应依赖目录名，而应依赖元数据选择 Skill。

```yaml
skill_id: cpp.performance.hot_path
domain: cpp
category: performance
tags:
  - hot_path
  - low_latency
  - allocation
capabilities:
  - code_generation
  - code_review
triggers:
  - write_code
  - refactor_code
context:
  language: cpp
  standard: ">=17"
priority: 90
```

### 15.4 Skill Pack

Skill Pack 用于管理常见组合。

```yaml
pack_id: cpp.safe_generation
includes:
  - cpp.base.*
  - cpp.safety.undefined_behavior
  - cpp.safety.lifetime
  - cpp.safety.ownership
  - cpp.error_handling
```

低延迟场景：

```yaml
pack_id: cpp.low_latency
extends:
  - cpp.safe_generation
includes:
  - cpp.performance.hot_path
  - cpp.performance.allocation
  - cpp.concurrency.data_race
overrides:
  - preference: performance > readability when hot_path
```

### 15.5 大规模激活流程

```text
Task Context
    ↓
Domain = cpp
    ↓
Select Candidate Packs
    ↓
Expand Packs into Skills
    ↓
Filter by tags / capabilities / context
    ↓
Rank by priority
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
```

---

## 16. Verification 与 Repair Loop

### 16.1 Verification 的意义

Skill 的基础阶段只是让 AI 阅读规则；进阶阶段是让规则参与系统执行。关键转变是：

```text
从“希望 AI 遵守规则”
转向
“验证 AI 是否遵守规则”
```

### 16.2 规则分流

不同规则应交由不同执行者处理。

| 规则类型 | 处理方式 |
|---|---|
| HARD | 静态分析、AST 检查、Lint、测试、Sanitizer |
| SOFT | LLM 自检、评分器、Review Agent |
| PREFERENCE | 多候选排序、Evaluator、人工选择 |

### 16.3 示例

```text
HARD: must not use strcpy
→ AST / regex / clang-tidy 检查

SOFT: prefer RAII
→ LLM review + heuristic checker

PREFERENCE: readability > cleverness
→ evaluator 排序
```

### 16.4 Repair Loop

```text
LLM Generation
    ↓
Verification
    ↓
Violation Report
    ↓
Repair Prompt
    ↓
LLM Repair
    ↓
Reverification
```

Repair Prompt 示例：

```text
The generated code violates the following HARD rules:
- Resource ownership is not explicit.
- Potential dangling reference detected.

Revise the code to satisfy these rules.
Do not change the public API unless necessary.
```

---

## 17. 推荐项目结构

```text
ai_policy_runtime/
│
├── skills/                         # Skill definitions
│   ├── platform/
│   │   └── safety.skill.yaml
│   ├── domain/
│   │   └── cpp/
│   │       ├── base/
│   │       ├── safety/
│   │       ├── concurrency/
│   │       ├── performance/
│   │       └── project_types/
│   ├── project/
│   │   └── low_latency_trading.skill.yaml
│   └── user/
│       └── preferences.skill.yaml
│
├── packs/                          # Skill Pack definitions
│   ├── cpp.safe_generation.yaml
│   └── cpp.low_latency.yaml
│
├── registry/                       # Skill Registry
│   ├── registry.py
│   ├── loader.py
│   ├── metadata.py
│   ├── lifecycle.py
│   └── versioning.py
│
├── task_analysis/                  # Task Analyzer
│   ├── analyzer.py
│   ├── deterministic_extractor.py
│   ├── llm_extractor.py
│   └── schema.py
│
├── activation/                     # Skill activation
│   ├── matcher.py
│   ├── context.py
│   ├── trigger.py
│   ├── dependency.py
│   └── pack_expander.py
│
├── rules/                          # Rule model and IR
│   ├── rule.py
│   ├── ir.py
│   ├── parser.py
│   └── normalizer.py
│
├── conflicts/                      # Conflict resolution
│   ├── classifier.py
│   ├── resolver.py
│   ├── policies.py
│   └── diagnostics.py
│
├── reduction/                      # Rule reduction
│   ├── reducer.py
│   ├── override.py
│   ├── deduplicate.py
│   ├── exceptions.py
│   └── preference_merge.py
│
├── runtime/                        # LLM / Agent runtime integration
│   ├── prompt_builder.py
│   ├── agent_runtime.py
│   ├── tool_router.py
│   └── execution.py
│
├── verification/                   # Rule verification
│   ├── ast/
│   ├── lint/
│   ├── evaluators/
│   ├── tests/
│   └── self_check.py
│
├── repair/                         # Repair loop
│   ├── critique.py
│   ├── repairer.py
│   └── retry.py
│
├── telemetry/                      # Observability
│   ├── traces.py
│   ├── metrics.py
│   └── logs.py
│
├── examples/
│   ├── cpp_low_latency.py
│   └── cpp_review.py
│
├── tests/
│   ├── test_activation.py
│   ├── test_conflicts.py
│   ├── test_reduction.py
│   └── test_effective_rules.py
│
└── main.py
```

---

## 18. 最小实现模块说明

前期最小实现可由以下模块组成。

### 18.1 skill.py

定义 Skill 数据结构，包括：

- skill_id；
- level；
- priority；
- domains；
- triggers；
- context；
- hard / soft / preference rules；
- dependencies；
- incompatibilities。

### 18.2 registry.py

负责注册和激活 Skills。

功能：

- register；
- load；
- domain match；
- trigger match；
- context match；
- dependency check。

### 18.3 engine.py

负责规则处理。

功能：

- rule extraction；
- normalization；
- conflict detection；
- conflict resolution；
- reduction；
- effective rule generation。

### 18.4 skills_data.py

示例 Skills，用于开发和测试。

### 18.5 main.py

演示完整流程：

```text
Task
  ↓
Registry Activation
  ↓
Rule Engine
  ↓
Effective Rules
```

这些脚本的作用不是实现业务逻辑，而是实现 Policy Runtime 的最小规则内核。

---

## 19. 工程落地路径

### 19.1 第一阶段：结构化 Skills

目标：让 Skills 从 Prompt 片段变为结构化规则文件。

产物：

- YAML Skill DSL；
- Skill Registry；
- Effective Rules 输出。

### 19.2 第二阶段：确定性激活与裁剪

目标：不再把所有 Skills 拼进 Prompt，而是自动选择当前任务相关 Skills。

产物：

- Task Context；
- Activation Engine；
- Conflict Resolver；
- Rule Reduction。

### 19.3 第三阶段：接入 LLM Runtime

目标：将 Effective Rules 注入 LLM 或 Agent Runtime。

产物：

- Prompt Builder；
- Agent Runtime API；
- Tool Router。

### 19.4 第四阶段：验证 HARD Rules

目标：将可判定规则映射到工具。

产物：

- clang-tidy；
- AST checks；
- lint；
- unit tests；
- sanitizer；
- custom validators。

### 19.5 第五阶段：Repair Loop

目标：当 AI 违反规则时，自动生成修复指令并重新验证。

产物：

- Violation Report；
- Repair Prompt；
- Revalidation Loop。

### 19.6 第六阶段：规模化管理

目标：管理大量 Domain Skills、Project Skills、User Preferences 和 Skill Packs。

产物：

- Skill Pack；
- versioning；
- lifecycle；
- telemetry；
- A/B testing；
- policy audit。

---

## 20. 设计边界与不完备性

### 20.1 理论上不完备

该系统不可能在形式逻辑意义上完备。原因包括：

- AI 面对开放世界任务；
- 用户意图常常不完整；
- 很多工程判断不可完全判定；
- “优雅”“合适”“不过度工程化”等概念无法被完全形式化；
- LLM 输出空间无法被有限规则完全覆盖。

### 20.2 工程上可以完备

虽然理论上不完备，但可以达到工程完备。工程完备意味着：

- 能表达主要约束类型；
- 能区分 HARD / SOFT / PREFERENCE；
- 能激活当前任务相关 Skills；
- 能检测和裁决主要冲突；
- 能生成最小有效规则集；
- 能把可验证规则交给工具执行；
- 能保留人类最终裁决空间。

### 20.3 不确定性的处理原则

系统不应试图消灭所有不确定性，而应管理不确定性：

- 可判定部分交给工具；
- 半判定部分交给 LLM 自检或评分；
- 不可判定部分保留为偏好排序或人工裁决；
- 冲突必须显式建模；
- 例外必须显式表达。

---

## 21. 结论

Skills 的最终形态不应只是 Prompt 模板，而应演化为 AI 系统中的策略与约束层。一个成熟的 Skill 系统需要包含：

- Skill DSL；
- Rule IR；
- Skill Registry；
- Task Analyzer；
- Activation Engine；
- Conflict Resolution；
- Rule Reduction；
- Effective Rules；
- Verification；
- Repair Loop；
- Skill Packs；
- Lifecycle Management。

其核心流程是：

```text
Skills
  → Registry 管理
  → Task Context 激活
  → Conflict Resolver 仲裁
  → Rule Reduction 压缩
  → Effective Rules 输出
  → LLM / Agent / Tools 执行
  → Verification 验证
  → Repair Loop 修复
```

该体系的关键价值在于：

> 将 AI 从自由生成器纳入工程约束系统，使其输出不再只依赖模型的临时理解，而是受到明确、可管理、可验证的策略层控制。

这套框架可以作为 Coding Agent、AI IDE、企业 AI 平台、多 Agent 系统、Tool Calling 系统和自动化工作流的通用 Policy Runtime 基础。
