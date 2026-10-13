# Task: Replace boto3 in S3Storage with a zero-dependency SigV4 S3 client

Outcome: the `s3` storage backend talks to S3/MinIO over a hand-rolled, stdlib-only
SigV4 client — removing boto3 (and transitively botocore + urllib3) from the `s3`
extra. Core stays zero-dep; `local` backend unchanged. Python is the reference;
PHP/Ruby/Node follow for parity.

## Scope (Python reference first)
- [ ] s3_client.py: SigV4 header signing + presigned-URL (query) signing (stdlib only)
- [ ] S3 ops used by S3Storage: PUT, GET, DELETE, HEAD, presigned GET URL
- [ ] Wire S3Storage to the new client (same public methods/behaviour)
- [ ] Remove boto3 from pyproject `s3` + `all-db`?/test extras; drop the lazy import
- [ ] Tests: SigV4 correctness vs AWS published test vectors (pure logic, not a mock)
      + real MinIO round-trip (no-mock) for put/get/url/delete/exists

## Parity
| Feature | Python | PHP | Ruby | Node |
|---------|--------|-----|------|------|
| zero-dep S3 client | ❌ | ❌ | ❌ | ❌ |

## Bugs
- [ ] Dependabot: urllib3 x3 (via botocore) cleared at root by removing boto3

## Commits
- (log here)

## Status: In Progress
Notes: path-style addressing (endpoint/bucket/key) — matches MinIO and works on AWS
for existing buckets; AWS default endpoint https://s3.<region>.amazonaws.com.
Signed headers: host, x-amz-content-sha256, x-amz-date. Presigned GET uses
UNSIGNED-PAYLOAD + X-Amz-* query params.
