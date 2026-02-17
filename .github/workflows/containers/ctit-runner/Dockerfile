FROM docker.io/library/ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    cmake \
    ninja-build \
    build-essential \
    python3 \
    python3-dev \
    python3-yaml \
    zlib1g-dev \
    zip \
    unzip \
    wget \
    git \
    ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create a new user with id 1001 as that is the user id that
# Github Actions uses to perform the checkout action.
RUN useradd gha -u 1001 -m -s /bin/bash
RUN usermod -aG sudo gha
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
USER gha
WORKDIR /home/gha
