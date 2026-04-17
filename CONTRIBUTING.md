# Contributing to HookReel

Thank you for your interest in contributing to HookReel!

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

### Running tests

docker exec hookreel python -m pytest \
  /hookreel/test_pipeline.py \
  /hookreel/test_phase5.py \
  /hookreel/test_phase7b.py \
  -v

To run the API tests (makes real DeepSeek API calls):
  HOOKREEL_RUN_API_TESTS=y docker exec -e HOOKREEL_RUN_API_TESTS=y hookreel \
    python -m pytest /hookreel/test_pipeline.py -v

### Making a change

1. Edit files in app/ on the host
2. docker compose restart hookreel
3. Verify with: docker logs hookreel --tail 20
4. Run the relevant test file

### Production usage

Production deployments pull the pre-built image from Docker Hub:
  docker compose up -d

Do not commit docker-compose.yml with build: . uncommented.
The image: nalbakri/hookreel:latest line must be active for releases.

## Reporting issues

Please open an issue on GitHub with:
- HookReel version (visible in the web UI nav bar)
- Docker and OS version
- Relevant logs: docker logs hookreel --tail 50
- Steps to reproduce

## Pull requests

- Keep changes focused -- one fix or feature per PR
- Run the full test suite before submitting
- Update CHANGELOG.md with a brief description of your change
- Plain ASCII only in all user-facing strings
