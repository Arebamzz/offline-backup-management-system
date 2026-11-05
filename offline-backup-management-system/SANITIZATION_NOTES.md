# Sanitization notes and publication checklist

This ZIP preserves the application source-code tree, including the Python GUI, Python services, legacy JavaScript modules, shell scripts, launcher assets and systemd examples. The original Git history is **not** included.

## Changes

- Changed internal host IPs to documentation-only IP addresses (`192.0.2.x`, `203.0.113.x`).
- Replaced company email addresses with `example.com` placeholders.
- Replaced environment-specific paths, user accounts, interfaces, disk UUID and internal system labels with generic examples.
- Moved the formerly active runtime JSON configuration into `config/pull-backup.template.json`; provided `config/pull-backup.example.json` with scrubbed values. Runtime `config/pull-backup.json` is excluded from Git.
- Removed `AGENTS.md` (internal operational/agent instructions) and `.activity_log.json` (runtime log artifact).
- Added `.gitignore` for credentials, SQLite runtime DB files, logs and build artifacts.
- Preserved service/cron scripts for source review; they are not deployment instructions.

## Check before sharing

- Get explicit permission from the company/code owner to share the underlying source, not only permission to redact secrets.
- Review the source for business logic, file names, operational schedules, internal workflow or customer information which should not be published.
- Inspect the GitHub upload/file diff. Never upload the original ZIP or an original config file into the public Git repository.
- Test in an isolated environment using **dummy data** and verify correct behavior; this sanitized version has not undergone integration testing.
- Paths containing `YOUR_PATH` and settings containing `YOUR_*` must be configured. Scripts that embed paths may require additional code changes for your target environment.
- README details and example systemd entries are descriptive only, not validated production deployment instructions.
