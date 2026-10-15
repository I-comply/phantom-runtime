# ruleid: phantom.docker.unpinned-base-image
FROM node:latest AS build
# ok: phantom.docker.unpinned-base-image
FROM node:20.11.1-alpine3.19
# ruleid: phantom.docker.unpinned-base-image
FROM ubuntu
# ok: phantom.docker.unpinned-base-image
FROM scratch
# ruleid: phantom.docker.pipe-to-shell
RUN curl -fsSL https://get.example.com | sh
# ok: phantom.docker.pipe-to-shell
RUN curl -fsSL https://get.example.com -o /tmp/i.sh && sha256sum -c sums && sh /tmp/i.sh
# ruleid: phantom.docker.add-remote-url
ADD https://example.com/app.tar.gz /opt/
# ok: phantom.docker.add-remote-url
ADD app.tar.gz /opt/
# ruleid: phantom.docker.secret-in-env
ENV API_TOKEN=abcd1234efgh
# ok: phantom.docker.secret-in-env
ARG API_TOKEN
# ruleid: phantom.docker.chmod-777
RUN chmod -R 777 /app
# ruleid: phantom.docker.apt-no-recommends
RUN apt-get install -y curl
# ok: phantom.docker.apt-no-recommends
RUN apt-get install -y --no-install-recommends curl
# ruleid: phantom.docker.expose-ssh
EXPOSE 22
# ruleid: phantom.docker.user-root
USER root
# ruleid: phantom.docker.missing-user
FROM alpine:3.19
CMD ["sh"]
