# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a vulnerability

Please do not report security vulnerabilities 
through public GitHub issues.

Instead, please report them by opening a 
GitHub Security Advisory:

1. Go to the Security tab of this repository
2. Click "Report a vulnerability"
3. Fill in the details

You should receive a response within 7 days.

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix if you have one

## What to report

Please report:
- Authentication bypasses in the web UI
- Path traversal vulnerabilities in file handling
- Credential exposure in logs or API responses
- Remote code execution possibilities
- Dependency vulnerabilities not yet addressed

## What not to report

The following are known design decisions, 
not vulnerabilities:

- HookReel is designed for single-user 
  home server use and is not hardened for 
  public internet exposure
- The web UI should be protected by Tailscale 
  or a reverse proxy — direct internet exposure 
  is not recommended
- VPN usage for downloads is the user's 
  responsibility

## Security recommendations for users

- Always use a strong web UI password
- Use Tailscale for remote access rather 
  than exposing ports
- Keep your .env file secure and never 
  commit it to git
- Enable VPN (Gluetun) for downloads
- Keep Docker images updated

## Disclosure policy

We follow responsible disclosure. Once a 
vulnerability is reported and confirmed 
we will:

1. Acknowledge receipt within 7 days
2. Investigate and develop a fix
3. Release a patch version
4. Credit the reporter in the changelog
   (unless they prefer to remain anonymous)
