# Security

## Reporting

Please report suspected vulnerabilities privately to the repository owner rather than opening a public issue with exploit details or credentials.

## Credential rotation notice

A historical revision of this repository contained a committed `.env` file. Removing the file from the current branch does not remove it from Git history.

Any deployment created from this repository before September 7, 2026 should treat the following credentials as compromised and rotate them before further use:

- `JWT_SECRET`
- the bootstrap administrator password
- any legacy service/API key copied from the historical `.env`

After rotation, invalidate existing JWT sessions and regenerate user API keys where appropriate. Do not commit runtime `.env` files or secret values to Git.

## API-key storage

Current API keys are generated from 256 bits of randomness and stored as deterministic SHA-256 digests so authentication can use a direct indexed lookup. Historical plaintext keys are upgraded to the digest format on successful authentication. Historical bcrypt-stored API keys are intentionally not scanned because doing bcrypt work for every user on an unauthenticated request creates a CPU-amplification denial-of-service path; those keys must be regenerated after JWT login.
