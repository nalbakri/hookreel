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
- Docker and Docker Compose
- Python 3.11+
- Git

### Getting started

1. Fork the repository
2. Clone your fork:
   git clone https://github.com/your-username/hookreel.git
   cd hookreel

3. Run the setup wizard:
   python3 setup.py

4. Start the stack:
   docker compose up -d

5. Run the test suite:
   docker cp test_pipeline.py hookreel:/hookreel/
   docker exec hookreel python -m pytest \
     /hookreel/test_pipeline.py -v

### Project structure

   app/              Python application modules
   app/templates/    Jinja2 HTML templates
   app/static/       CSS, JS, images
   config/           Configuration (.env file)
   docs/             Documentation
   setup.py          Interactive setup wizard
   import_library.py Library import tool
   main.py           Application entry point

### Making changes

- Keep changes focused — one feature or fix per pull request
- Follow the existing code style:
  - Docstrings on every function
  - Clear variable names, no abbreviations
  - All log messages prefixed with [HookReel]
  - Handle exceptions gracefully
- Add tests for new functionality in the appropriate 
  test_phase*.py file
- Update documentation if your change affects 
  user-facing behaviour

### Submitting a pull request

1. Create a branch:
   git checkout -b fix/your-fix-name

2. Make your changes and test them

3. Commit with a clear message:
   git commit -m "Brief description of change"

4. Push and open a pull request against master

5. Describe what your change does and why

## Reporting bugs

Please use the Bug Report issue template and include:
- HookReel version (shown in web UI footer)
- Your setup (OS, Docker version, AI model)
- Steps to reproduce
- Expected vs actual behaviour
- Relevant logs from docker logs hookreel

## Suggesting features

Please use the Feature Request issue template.
Describe the use case, not just the feature — 
help us understand why it would be useful.

## Code of Conduct

This project follows the Contributor Covenant Code of Conduct.
By participating you are expected to uphold this standard.

## Questions

Open a GitHub Discussion or raise an issue tagged 
as a question.
