FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG BOOST_VERSION=1.91.0
ARG BOOST_DIR=boost_1_91_0
ARG OPENSSL_VERSION=4.0.1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc-14 g++-14 cmake ninja-build git wget ca-certificates \
    ccache perl pkg-config bzip2 libbz2-dev libreadline-dev zlib1g-dev \
    default-libmysqlclient-dev default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q "https://archives.boost.io/release/${BOOST_VERSION}/source/${BOOST_DIR}.tar.gz" \
    && tar -xzf "${BOOST_DIR}.tar.gz" \
    && cd "${BOOST_DIR}" \
    && ./bootstrap.sh \
    && ./b2 install --prefix="/opt/${BOOST_DIR}" --with-headers -j"$(nproc)" \
    && cd / \
    && rm -rf "/${BOOST_DIR}" "/${BOOST_DIR}.tar.gz"

RUN wget -q "https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz" \
    && tar -xzf "openssl-${OPENSSL_VERSION}.tar.gz" \
    && cd "openssl-${OPENSSL_VERSION}" \
    && ./Configure linux-x86_64 \
       --prefix="/opt/openssl-${OPENSSL_VERSION}" \
       --openssldir="/opt/openssl-${OPENSSL_VERSION}/ssl" \
       shared enable-legacy \
    && make -j"$(nproc)" \
    && make install_sw install_ssldirs \
    && cd / \
    && rm -rf "/openssl-${OPENSSL_VERSION}" "/openssl-${OPENSSL_VERSION}.tar.gz"

ENV CC=gcc-14
ENV CXX=g++-14
ENV BOOST_ROOT=/opt/boost_1_91_0
ENV OPENSSL_ROOT_DIR=/opt/openssl-4.0.1
ENV LD_LIBRARY_PATH=/opt/openssl-4.0.1/lib64:/opt/openssl-4.0.1/lib
ENV CCACHE_DIR=/cache/ccache
ENV CCACHE_MAXSIZE=5G

WORKDIR /workspace

COPY .ci/module-build/build-inner.sh /usr/local/bin/build-module
RUN chmod +x /usr/local/bin/build-module

ENTRYPOINT ["build-module"]
