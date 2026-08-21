# Task: Graph database layer (Feature 139) — release 3.13.111

Outcome: a `GraphDatabase` layer shaped exactly like the relational `Database`
layer — URL-selected adapter, `create()`/`fromEnv()`, one portable
node/edge/traverse surface + a raw `query`/`execute` pass-through, neutral
`GraphNode`/`GraphEdge`/`GraphResult`. `.111` ships the **Ultipa** engine across
all four frameworks, proven against the live Ultipa community edition on the lab
(192.168.88.99:60061). Neo4j/Memgraph/Arango adapters are `.112+` (need lab
provisioning). Governed by ADR-0059 + `tina4-documentation/plan/v3/features/139-graph-databases.md`
+ `fixtures/graph_contract.json`.

## Scope (Python reference first, then parity)
- [ ] Python: `tina4_python/graph/` module mirroring `database/`
  - [ ] `GraphUrl` parser (scheme/host/port/graph/user/pass/params) — mirror `DatabaseUrl`
  - [ ] neutral shapes `GraphNode{id,labels,properties}`, `GraphEdge{id,type,from,to,properties}`, `GraphResult{records,columns}`
  - [ ] `GraphAdapter` interface (addNode/addEdge/getNode/updateNode/deleteNode/neighbors/traverse/query/execute/close/get_error) — raising stubs
  - [ ] `GraphDatabase.create(url, username, password)` + `fromEnv()` — scheme→adapter, lazy+guarded driver import
  - [ ] connect-timeout: `TINA4_GRAPH_CONNECT_TIMEOUT` (sibling of the relational contract), reuse the same bound/message pattern
  - [ ] `adapters/ultipa.py` `UltipaGraphAdapter` — wraps `tina4_ultipa.UltipaClient`, builds the portable core in GQL on top of `query`/`execute`; raw pass-through sends GQL directly
- [ ] PHP / Ruby / Node: port the same module + Ultipa adapter (Python is the reference)

## Parity (.111 ships ALL FOUR engines)
| Engine | Python | PHP | Ruby | Node |
|--------|--------|-----|------|------|
| Ultipa (GQL)          | ✅ proven live | 🔄 port | 🔄 port | 🔄 port |
| Neo4j (Bolt/Cypher)   | ✅ proven live | ❌ | ❌ | ❌ |
| Memgraph (Bolt/Cypher)| ✅ proven live | ❌ | ❌ | ❌ |
| ArangoDB (AQL)        | ✅ proven live | ❌ | ❌ | ❌ |

Python reference PROVEN on the lab against ALL FOUR live engines (no mocks):
`pytest test_graph.py` = **39 passed** parametrised over Ultipa (gqldb 6.2.130,
:60071), Neo4j 5 (:7687), Memgraph (:7688), ArangoDB (:8529). Engine-specific
learnings: Ultipa GQL `INSERT..RETURN id(n)` (UUID ids) + quantified path
`-[]->{1,N}` + EDGE_ID; Bolt/Cypher `CREATE..RETURN id(n)` (int ids) + `[*1..N]`
+ `SET n += $props` (one adapter serves Neo4j AND Memgraph); Arango AQL document
model (one vertex + one edge collection, `_labels`/`_type` fields, `FOR v IN
1..N OUTBOUND`, `LIMIT` before `RETURN`). Drivers are optional extras
(`[ultipa]`/`[neo4j]`/`[arango]`/`[graph]`).

Python reference PROVEN on the lab against live Ultipa community edition
(gqldb 6.2.130, 192.168.88.99:60071, graph `default`): `test_graph.py` → 12
passed. Validated GQL: `INSERT (n:label {..}) RETURN id(n)/labels(n)/properties(n)`
(node ids are UUID strings); edges need `EDGE_ID` enabled (`ALTER GRAPH x SET
EDGE_ID ENABLED`); traversal uses GQL quantified paths `-[]->{1,N}` (NOT Cypher
`[*1..N]`); read/write split enforced by the driver's read_only flag.

## Tests (real, no-mocks, against live Ultipa on the lab; contract case names)
- [ ] graph-connect-by-url — a URL scheme selects the right adapter and connects
- [ ] graph-add-node — addNode returns a node with an id, labels and properties
- [ ] graph-add-edge — addEdge links two nodes with a type and properties
- [ ] graph-get-node — round-trips stored properties; miss returns falsy (not error)
- [ ] graph-update-delete-node — updateNode merges (re-read); deleteNode removes (re-read miss)
- [ ] graph-neighbors — connected nodes filtered by direction + edge type; unmatched → empty
- [ ] graph-traverse-depth — reachable set within N hops
- [ ] graph-raw-query — native GQL round-trips through query() with bound params
- [ ] graph-write-fails-loud — bad raw statement RAISES; cause on get_error()
- [ ] graph-driver-optional — missing driver → actionable install error; core imports driver-free
- [ ] graph-connect-timeout — unreachable host throws within TINA4_GRAPH_CONNECT_TIMEOUT, names host/port/elapsed

## Bugs
- [ ] (log here)

## Commits
- (hash  description)

## Status: In Progress
