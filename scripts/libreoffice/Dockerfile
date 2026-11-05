# Headless LibreOffice for PPTX -> PDF conversion (prep/convert.py).
# Nothing is installed on the host: the prep code runs this image with `docker run`.
# Build: scripts/libreoffice/build.sh
FROM debian:trixie-slim

# Impress only (no GUI recommends) plus fonts that are metric-compatible with the
# common Office fonts (Arial/Times/Courier -> Liberation, Calibri -> Carlito,
# Cambria -> Caladea), so text positions in the PDF stay close to the PPTX.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress \
        fonts-liberation \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user; HOME holds the throwaway LibreOffice profile.
RUN useradd --create-home --home-dir /var/lib/office --uid 1000 office
USER office
ENV HOME=/var/lib/office
WORKDIR /work

ENTRYPOINT ["soffice", "--headless", "--norestore", "--nolockcheck"]
