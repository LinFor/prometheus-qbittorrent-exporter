FROM alpine

# Installing required packages
RUN apk add --update --no-cache \
    python3 \
    py3-pip

# Install package
WORKDIR /code
COPY . .
RUN pip3 install .

ENV QBITTORRENT_HOST=""
ENV QBITTORRENT_PORT=""
ENV QBITTORRENT_USER=""
ENV QBITTORRENT_PASS=""
ENV EXPORTER_PORT="8000"
ENV EXPORTER_LOG_LEVEL="INFO"

ENTRYPOINT ["qbittorrent-exporter"]
