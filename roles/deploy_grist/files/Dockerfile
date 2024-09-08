ARG APP_VERSION

FROM gristlabs/grist:${APP_VERSION}

RUN \
  apt update && apt install -y openssl && \
  python3 -m pip install numpy
