# Contract: the `brain-worker` command

The worker's only interface (FR-009, FR-010, FR-010a; research R-04, R-05). There is no HTTP
endpoint and no screen button that runs a job (D-38).

| Command | What it does | Exit code |
|---|---|---|
| `brain-worker serve` | The container's default command. Starts the Africa/Cairo scheduler: `sales-poll` at minute `*/5`, `hourly-window` at minute 7, `end-of-day` at 02:00 (P-5, approved). On start, runs a missed `end-of-day` once (trigger `catch-up`) | runs until stopped |
| `brain-worker run sales-poll` | One sales poll now | 0 done; 1 failed; 3 already running |
| `brain-worker run hourly-window` | One hourly window now | 0, 1 or 3 |
| `brain-worker run end-of-day` | One end-of-day run now (starts with a sales poll) | 0, 1 or 3 |
| `brain-worker reset [--yes]` | Empties every Brain table after typing `RESET` (or at once with `--yes`). Not a job | 0 done; 2 cancelled; 3 a job is running |
| `brain-worker healthcheck` | Compose's health check: the worker database answers and the Brain migrations are at head. Not a job | 0 healthy; 1 not |

Any other job name is refused with the list of the three, exit code 2.

## Output

One line per run on stdout, for example:

```text
end-of-day trigger=manual status=succeeded products=20 lgbm_chosen=11 anomalies_found=5 results=20 kept=0 took=14.2s
```

Never the service token, the `Authorization` header or a password. Failures name the Canonical
operation and the HTTP status (for example `GET /purchase-orders 503`).

## Running it

```bash
docker compose exec brain-worker brain-worker run end-of-day
```
