#!/usr/bin/env bash
# Build the headless LibreOffice image used by `prep convert` for PPTX -> PDF.
# The tag must match `parse.libreoffice_image` in config/settings.yaml.
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:-classpilot-libreoffice:1}"
docker build -t "$TAG" .
docker run --rm "$TAG" --version
