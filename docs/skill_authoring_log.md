# Skill Authoring Log

## English-Only DSL Boundary

Skill DSL files under `skills/` are canonical policy assets and must stay in
English. Do not add translated trigger phrases, aliases, semantic examples, rule
text, rationale, or authoring notes to Skill YAML.

Multilingual task understanding belongs to the embedding provider and semantic
analysis layer. When a common non-English request fails to recall the right
Effective Rules, fix it by adding better English semantic anchors that describe
the everyday intent, then add multilingual recall tests. Do not duplicate the
user's language inside the Skill DSL.

Incident note: a daily request equivalent to "commit code changes" once failed
to activate Git Effective Rules. The correct fix was to add English Git commit
semantic anchors and semantic bootstrap logic, while keeping the Skill DSL
English-only.
