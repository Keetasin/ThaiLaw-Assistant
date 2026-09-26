# Graph schema diagram

```mermaid
flowchart TD
  Law --> Chapter --> Section
  Section -->|REFERS_TO| Section
  Section -->|PENALIZED_BY| Section
  Section -->|DEFINES / USES_TERM| Term
  Section -->|ABOUT| Topic
  Topic --> Agency
  Topic --> Evidence
  Topic --> Form
  Topic --> Step
  Section --> Right
  Section --> Duty
  Section --> Penalty
  Right --> Actor
  Duty --> Actor
```

The offline graph artifact is `data/graph.json`; `visualisation.svg` contains
the generated graph view. A live Neo4j Browser capture remains pending until
the Docker/Neo4j service is available.
