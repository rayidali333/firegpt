# Stage 1: Build React frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Build LibreDWG for DWG-to-DXF conversion
FROM python:3.11-slim AS libredwg-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git autoconf automake libtool texinfo && \
    rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/LibreDWG/libredwg.git /tmp/libredwg && \
    cd /tmp/libredwg && \
    autoreconf -fi && \
    ./configure --prefix=/usr/local --disable-bindings --disable-write && \
    make -j$(nproc) -C src && \
    make -j$(nproc) -C programs && \
    make install -C src && \
    make install -C programs

# Stage 3: Python backend + serve frontend
FROM python:3.11-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy LibreDWG binaries and libraries from build stage
COPY --from=libredwg-build /usr/local/bin/dwg2dxf /usr/local/bin/dwg2dxf
COPY --from=libredwg-build /usr/local/lib/libredwg* /usr/local/lib/
RUN ldconfig

COPY backend/ ./
COPY --from=frontend-build /app/frontend/build ./static

RUN mkdir -p /app/uploads

ENV PORT=8000
EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
