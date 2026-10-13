# Claude Code episode image with matplotlib, used for the paper's Claude Opus 5 run.
# The paper's mini-SWE-agent episodes ran on the host (Python 3.9, matplotlib 3.9.4, Pillow 11.3.0,
# whose PNG encoder uses zlib-ng). The base image (Dockerfile) has no matplotlib, so agents could not
# re-render the tasks' PNG charts. This image adds matplotlib 3.9.4 and Pillow 11.3.0 and replaces the
# system zlib that Pillow links with zlib-ng 2.2.4 in zlib-compatible mode. With plain zlib,
# re-rendered charts are pixel-identical to the shipped ones but not byte-identical; with zlib-ng
# 2.2.4 they are byte-identical. Packages are installed at build time; episodes run with the network off.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS zbuild
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch 2.2.4 https://github.com/zlib-ng/zlib-ng /src && cmake -S /src -B /b -DZLIB_COMPAT=ON -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF && cmake --build /b -j4 && cp -L /b/libz.so.1 /libz-ng-compat.so.1

FROM reconcilebench-claude-code:2.1.289
USER root
RUN pip install --no-cache-dir matplotlib==3.9.4 pillow==11.3.0
COPY --from=zbuild /libz-ng-compat.so.1 /tmp/libz-ng-compat.so.1
# Pillow links the system zlib (/usr/lib/<arch>/libz.so.1.3.1), so the zlib-ng build replaces that file;
# zlib-ng's compat build has the same ABI. Every process sees it, with no environment variable needed.
RUN set -e; f=$(readlink -f "$(ldconfig -p | awk '/libz.so.1 /{print $NF; exit}')"); echo "replacing $f"; \
    cp /tmp/libz-ng-compat.so.1 "$f"; rm /tmp/libz-ng-compat.so.1; ldconfig; \
    python3 -c "from PIL import features; import matplotlib, PIL; v=features.version('zlib'); print('matplotlib', matplotlib.__version__, 'Pillow', PIL.__version__, 'zlib', v); assert 'zlib-ng' in v"
USER agent
WORKDIR /workspace
