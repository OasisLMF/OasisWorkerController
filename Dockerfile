FROM python:3.8

ENV NETWORK host
ENV QUEUE_CONFIG_PATH ./config.json
ENV PYTHONUNBUFFERED 1

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
RUN usermod -a -G docker controller
# USER controller
#     this casuse Socket access problems if here is a mismatch between the docker group id in the container and the host
#     Possible fix is to pass the docker group id in to the build process,
#     however that would require local builds for each user
WORKDIR /home/controller

COPY --chown=controller ./config.json /home/controller
COPY --chown=controller src/ ./src/

ENTRYPOINT [ "./src/controller.py" ]
