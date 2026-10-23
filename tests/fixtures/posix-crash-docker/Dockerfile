# Fixture image for tests/test_posix_docker_crash.py (#597): the real-Docker tier of the posix
# launch crash tests. Base pinned by digest (alpine:3.20, resolved 2026-10-23); git from Alpine's
# repository at build time; `claude` is an INERT script that never contacts a model.
FROM alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
RUN apk add --no-cache git
COPY claude /usr/local/bin/claude
RUN chmod 0755 /usr/local/bin/claude
