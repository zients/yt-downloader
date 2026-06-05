# Security Policy

## Supported Use

This project is intended for personal self-hosting or trusted-LAN use. It is not
designed to be exposed directly to the public internet.

If you deploy this application outside a trusted network, add your own
authentication, authorization, rate limiting, monitoring, TLS termination, and
resource controls before making it reachable by other users.

## Responsible Use

This application can create network, CPU, and disk load while downloading and
converting media. Operators are responsible for:

- Running it only in environments where users are trusted.
- Following applicable laws, copyright rules, and platform terms of service.
- Controlling who can create download and conversion jobs.
- Monitoring disk usage and removing generated files when needed.

Please do not use this project to operate a public downloader service.

## Reporting a Vulnerability

If you find a security issue, please do not open a public issue with exploit
details.

Use GitHub private vulnerability reporting if it is enabled for this repository.
If it is not available, contact the maintainer through GitHub without posting
exploit details publicly.

Include enough detail to reproduce and evaluate the issue:

- Affected version, commit, or branch.
- Deployment mode and relevant configuration.
- Steps to reproduce.
- Expected and actual behavior.
- Impact and any suggested mitigation.

I will review reports as time allows and follow up when I can reproduce or
triage the issue.

## Out of Scope

The following are generally out of scope for security reporting:

- Issues that require intentionally exposing the service to untrusted users
  without authentication or rate limiting.
- Abuse reports about content downloaded by an operator or user of a private
  deployment.
- Platform access failures caused by upstream services, account restrictions, or
  yt-dlp behavior.
- Denial-of-service scenarios caused by giving untrusted users access to a
  trusted-LAN tool without additional controls.
