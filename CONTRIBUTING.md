# Contributing to HookReel

Thank you for your interest in contributing to HookReel!

## Ways to contribute

- Report bugs via GitHub Issues
- Suggest features via GitHub Issues
- Submit pull requests for bug fixes
- Improve documentation
- Share HookReel with other self-hosters

## Before you start

Please check the existing issues and pull requests
before opening a new one to avoid duplicates.

## Development setup

### Prerequisites
- Docker and Docker Compose v2+
- Python 3.11+
- Git

### Getting started

1. Fork and clone the repository:
   git clone https://github.com/nalbakri/hookreel
   cd hookreel

2. Run the setup wizard to configure your environment:
   python3 setup.py

3. For development, use the dev compose override to mount the app
   directory live into the container:
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

4. Changes to app/ on the host are reflected immediately after:
   docker compose restart hookreel

### Project structure

   app/              Python application modules
   app/templates/    Jinja2 HTML templates
   app/static/       CSS, JS, images
   config/           Configuration (.env file)
   docs/             Documentation
   setup.py          Interactive setup wizard
   main.py           Application entry point

### Running tests

   docker exec hookreel python -m pytest \
     /hookreel/test_pipeline.py \
     /hookreel/test_phase7b.py \
     /hookreel/test_patch1.py \
     -v

To run the API tests (makes real DeepSeek API calls):
   HOOKREEL_RUN_API_TESTS=y docker exec -e HOOKREEL_RUN_API_TESTS=y hookreel \
     python -m pytest /hookreel/test_pipeline.py -v

### Making changes

- Keep changes focused -- one fix or feature per PR
- Follow the existing code style:
  - Docstrings on every function
  - Clear variable names, no abbreviations
  - All log messages prefixed with [HookReel]
  - Handle exceptions gracefully
- Add tests for new functionality
- Update CHANGELOG.md with a brief description of your change
- Plain ASCII only in all user-facing strings

### Production usage

Production deployments pull the pre-built image from Docker Hub:
   docker compose up -d

Do not commit docker-compose.yml with build: . uncommented.
The image: nalbakri/hookreel:latest line must be active for releases.

## Submitting a pull request

1. Create a branch:
   git checkout -b fix/your-fix-name

2. Make your changes and test them

3. Commit with a clear message:
   git commit -m "Brief description of change"

4. Push and open a pull request against master

5. Describe what your change does and why

## Reporting bugs

Please use the Bug Report issue template and include:
- HookReel version (shown in web UI nav bar)
- Your setup (OS, Docker version, AI model)
- Steps to reproduce
- Expected vs actual behaviour
- Relevant logs: docker logs hookreel --tail 50

## Suggesting features

Please use the Feature Request issue template.
Describe the use case, not just the feature.

## Code of Conduct

This project follows the Contributor Covenant Code of Conduct.
By participating you are expected to uphold this standard.

## Questions

Open a GitHub Discussion or raise an issue tagged as a question.
