# Security policy

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public issue.

After the repository is published, use GitHub's **Security** tab to open a private security advisory. Include the affected version, reproduction steps, impact, and any proposed mitigation. Avoid attaching real cached indexes, `.oder` files, credentials, private URLs, or downloaded content unless they have been sanitized.

There is currently no guaranteed response or remediation timeframe. Maintainers should acknowledge a private report, reproduce it, prepare a fix, and coordinate disclosure before publishing details.

## Sensitive local data

ODeR stores profiles, directory URLs, cached indexes, crawl state, logs, queue history, and downloads under `data/`. That directory and common database/package artifacts are excluded by `.gitignore`; contributors should still inspect changes before every commit.
