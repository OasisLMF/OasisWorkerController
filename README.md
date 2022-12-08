> WARNING: This repository has been replaced with a kubernetes version stored in [OasisPlatform/kubernetes/worker-controller](https://github.com/OasisLMF/OasisPlatform/tree/platform-2.0/kubernetes/worker-controller)

# Oasis worker controller

This is an example of how you can control workers in your oasis deployment.

The process connects to the websocket in the api and monitors it for changes
in the queue utilization.

In this example we monitor the socket and as the number of queued tasks increase
we create a new container to process that queue. When the number of queues and
pending tasks decrease the task worker containers are stopped.

## Installation

Running the controller requires docker compose:

    $ pip install docker-compose
    
## Building the image

You can build the image using:

    $ docker-compose build
    
## Running the controller

The docker compose config takes a set of local environment variables and passes 
them into the controller. These are:

| Name | Description | Default |
|------|-------------|---------|
| `OASIS_API_HOST` | The hostname and port of the oasisi api endpoint | `localhost:8000` |
| `OASIS_BROKER_URL` | The url for the celery broker | `amqp://rabbit:rabbit@localhost:5672` | 
| `OASIS_ADMIN_USER` | The username of the user to use for authentication against the api | `admin` |
| `OASIS_ADMIN_PASS` | The password of the user to use for authentication against the api | `password` |
| `DOCKER_SOCKET_LOCATION` | The location of the docker socket to mount in the container | `/var/run/docker.sock` |
| `OASIS_MODEL_DATA_DIR` | The absolute path to the PiWind data on the host machine | |
| `OASIS_MEDIA_ROOT` | The absolute path to the shared filesystem on the host machine | |

The docker container created by `docker-compose` and the created containers will
be on the `host` network so any reference to `localhost` will refer to the host
machine.

## License

The code in this project is licensed under BSD 3-clause license.
