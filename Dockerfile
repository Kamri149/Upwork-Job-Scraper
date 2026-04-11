FROM python:3.13-slim

WORKDIR /app

# Install dependencies (cached layer). Minimal src/ stub lets setuptools build.
COPY pyproject.toml .
RUN mkdir -p src && touch src/__init__.py \
    && pip install --no-cache-dir .

# Copy real source (invalidates only on code changes)
COPY src/ src/

CMD ["python", "-m", "src.controllers.scraper_controller"]
