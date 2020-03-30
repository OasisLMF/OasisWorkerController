FROM python:3.8

ENV NETWORK bridge
ENV QUEUE_CONFIG_PATH ./config.json

RUN apt update && apt install apt-transport-https \
                              ca-certificates \
                              curl \
                              gnupg2 \
                              software-properties-common \
                              -y --no-install-recommends && \
                              rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add -
RUN apt-key fingerprint 0EBFCD88
RUN add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/debian $(lsb_release -cs) stable"
RUN apt update && apt install docker-ce \
                              docker-ce-cli \
                              containerd.io \
                              -y --no-install-recommends && \
                              rm -rf /var/lib/apt/lists/*

COPY requirements-controller.txt .
RUN pip install -r requirements-controller.txt

RUN useradd controller
USER controller
WORKDIR /home/controller

COPY --chown=controller src/ ./src/

ENTRYPOINT [ "./src/controller.py" ]
