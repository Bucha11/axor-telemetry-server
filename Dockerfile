FROM python:3.12-slim

WORKDIR /srv

# Metadata + source needed by hatchling to build the wheel.
# README.md is validated by hatchling because pyproject.toml's [project]
# table references it; omitting it makes the build fail.
COPY pyproject.toml README.md ./
COPY app ./app

# Non-editable install — this is a production image, not a dev checkout.
RUN pip install --no-cache-dir .

# Runtime assets that are not part of the Python package.
COPY migrations ./migrations

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
