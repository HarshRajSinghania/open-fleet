# The open-fleet live harness image (PR #668): every paid live arm runs in a fresh container of
# it, which scripts/live_container.py destroys after. Build it with `live_container.py build`,
# the only step that downloads anything (docs/guides/live-harness.md). It holds no credential:
# the subscription token reaches a container at run time as a read-only file, never this image.
#
# The base is pinned by digest: python:3.13.15-slim's OCI image index, one pin on every platform it carries.
FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# git for the arms (each reads its own checkout's HEAD); curl and certificates for the installer.
# `runner` (10001) is the non-root user every arm runs as; /repo is a read-only mount it does not own.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 runner \
 && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash runner \
 && git config --system --add safe.directory /repo

USER runner
ENV HOME=/home/runner \
    PATH=/home/runner/.local/bin:/usr/local/bin:/usr/bin:/bin \
    DISABLE_AUTOUPDATER=1 \
    PYTHONDONTWRITEBYTECODE=1

# Claude Code, pinned, by its official installer, as `runner`. The installer is saved to a file and
# runs only when its sha256 is the pinned one, never piped to a shell; the build then fails unless
# the binary the in-container wrapper execs (scripts/live_container_bin/claude) has the sha256 the
# 2.1.304 release manifest gives for this platform, and is that version (2026-10-27 audit, W5-12).
# Re-pin both on a version bump: sha256 of https://claude.ai/install.sh, and the linux-x64 and
# linux-arm64 checksums in https://downloads.claude.ai/claude-code-releases/<version>/manifest.json.
RUN curl -fsSL -o /tmp/claude-install.sh https://claude.ai/install.sh \
 && echo "3a68d3406cf674e17bed1733a4dcf37805e2e47d87417700007d7e1aa766a944  /tmp/claude-install.sh" | sha256sum -c - \
 && bash /tmp/claude-install.sh 2.1.304 \
 && rm -f /tmp/claude-install.sh \
 && case "$(uname -m)" in \
      x86_64) want=ea0f135784631619a7a409d07322ecec964f9cc4fd377508ed1ba3f141f27912 ;; \
      aarch64) want=c487117526509ab6d2ee6013e14f181faf68d6d6afe6bb0d4b2b4a9feca5ecb3 ;; \
      *) echo "no pinned Claude Code 2.1.304 digest for $(uname -m)" >&2; exit 1 ;; \
    esac \
 && echo "$want  /home/runner/.local/share/claude/versions/2.1.304" | sha256sum -c - \
 && /home/runner/.local/share/claude/versions/2.1.304 --version | grep -q '^2\.1\.304 '

LABEL org.open-fleet.claude-code="2.1.304"
WORKDIR /results
