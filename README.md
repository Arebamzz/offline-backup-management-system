# Offline Backup Management System

A Python-based offline backup and document synchronization system designed and developed from scratch to automate backup operations, monitor scheduled jobs, and manage file transfers through a desktop interface.

## Overview

The Offline Backup Management System provides a centralized solution for managing automated database backups and document synchronization across Linux-based environments.

The system combines a Python desktop application, backup automation scripts, remote synchronization, and scheduled services to reduce manual operations and improve backup reliability.

## Key Features

- **Automated Backup Scheduling** — Executes scheduled backup operations using Linux systemd services and timers.
- **Desktop Monitoring GUI** — Provides a PySide6 interface to monitor backup activities, job status, and synchronization information.
- **Full and Incremental Backups** — Uses rsync to transfer files efficiently and minimize redundant data transfers.
- **Document Synchronization** — Manages document and image backups between configured storage locations.
- **Remote Server Support** — Supports secure file synchronization through SSH.
- **Real-Time Activity Logging** — Displays backup progress and activity logs through HTTP and WebSocket-based services.
- **Transfer Queue Management** — Organizes file transfers with queue-based processing and retry handling.
- **Configuration Management** — Uses JSON and SQLite for system configuration and operational metadata.

## Technology Stack

| Category | Technologies |
|---|---|
| Programming Languages | Python, JavaScript, Bash |
| Desktop Application | PySide6 / Qt |
| Backup & Synchronization | rsync, SSH |
| Backend Services | Python, Node.js, aiohttp |
| Database | SQLite |
| Scheduling | Linux systemd |
| Communication | HTTP, WebSocket |
| Operating System | Ubuntu / Linux |

## System Architecture

The system follows a modular architecture:

1. **Desktop GUI** — Displays backup jobs, schedules, status, and activity logs.
2. **Backup Orchestrator** — Coordinates backup operations and processes.
3. **Synchronization Engine** — Transfers files using rsync and SSH.
4. **Configuration Layer** — Manages backup destinations and settings.
5. **Logging Service** — Records and streams operational activity.
6. **Scheduler** — Executes automated backup tasks using systemd.

## Project Structure

```text
offline-backup-management-system/
├── bin/            # Desktop GUI and executable utilities
├── config/         # Configuration templates
├── scripts/        # Backup and installation scripts
├── src/            # Core backup and synchronization modules
├── systemd/        # Linux service and timer definitions
└── README.md       # Project documentation
```

## Security and Configuration

Environment-specific information, including server addresses, credentials, storage paths, and internal infrastructure details, should be configured separately.

Sample configurations use placeholder values and must be customized before deployment.

## My Role

**Sole Developer — Designed and Developed from Scratch**

- Designed the system architecture and backup workflows.
- Developed the Python desktop GUI for backup monitoring.
- Implemented automated backup and document synchronization processes.
- Integrated rsync, SSH, systemd scheduling, and real-time logging.
- Built configuration management and transfer queue workflows.
- Troubleshot and improved backup reliability across Linux environments.

## Project Status

Developed as a practical backup automation and management solution. This repository is intended to document the system's architecture, implementation, and development work.

## Author

**Arebamzz**

Software Developer | Python | Automation | Linux | Backend Development
