#!/usr/bin/env python

"""
This is an example of how you can control workers in your oasis deployment.

The process connects to the websocket in the api and monitors it for changes
in the queue utilization.

In this example we monitor the socket and as the number of queued tasks increase
we create a new container to process that queue. When the number of queues and
pending tasks decrease the task worker containers are stopped.
"""

import argparse
import asyncio
import json
from uuid import uuid4
from typing import Dict, List, TypedDict
from urllib.parse import urljoin

import aiohttp
from os import getenv
import websockets
from aiohttp import ClientError
import os


class SocketQueueEntry(TypedDict):
    """
    Type describing the used parts of the queue info
    """
    name: str
    pending_count: int
    worker_count: int
    queued_count: int
    running_count: int


class SocketContentEntry(TypedDict):
    """
    Type describing the used parts of an entry in the web socket message
    """
    queue: SocketQueueEntry


class SocketMessage(TypedDict):
    """
    Type describing the used parts of the socket message
    """
    content: List[SocketContentEntry]


# state holding a mapping of queues to a list of containers for that queue
state: Dict[str, List[str]] = {}


class ContainerConfig(TypedDict):
    """
    Type describing the information held about a the controlled queues
    """
    image: str
    env: Dict[str, str]
    volumes: Dict[str, str]


# config holding a mapping of queues to container configuration
ControllerConfig = Dict[str, ContainerConfig]


def parse_args():
    parser = argparse.ArgumentParser('Oasis example model worker controller')
    parser.add_argument('--api-host', help='The root uri of the api to connect to.', default=getenv('API_HOST'))
    parser.add_argument('--username', help='The username of the worker controller user.', default=getenv('USERNAME'))
    parser.add_argument('--password', help='The password of the worker controller user.', default=getenv('PASSWORD'))
    parser.add_argument('--config', help='File path to the config mapping queue name to docker image name.', type=os.path.abspath, default=getenv('QUEUE_CONFIG_PATH', './config.json'))
    parser.add_argument('--network', help='The name of the docker network to run the workers on.', default=getenv('NETWORK', 'host'))
    parser.add_argument('--broker', help='The uri of the broker managing celery tasks.', default=getenv('BROKER_URI'))
    parser.add_argument('--secure', help='Flag if https and wss should be used.', default=False, action='store_true')
    return parser.parse_args()


class Connection:
    """
    Handles connecting to the websocket. Before connecting to the socket we
    first fetch the access token from the server to authenticate the websocket.
    """
    def __init__(self, api_host, username=None, password=None, secure=False):
        self.username = username
        self.password = password
        self.api_host = api_host
        self.secure = secure
        self.http_scheme = 'https://' if secure else 'http://'
        self.ws_scheme = 'wss://' if secure else 'ws://'
        self.connection = None

    async def __aenter__(self):
        """
        Authenticates against the api and connects to the websocket.
        """
        async with aiohttp.ClientSession(loop=asyncio.get_event_loop()) as session:
            params = {'username': self.username, 'password': self.password}

            async with session.post(urljoin(f'{self.http_scheme}{self.api_host}', '/access_token/'), data=params) as resp:
                raw = (await resp.content.read()).decode()
                if resp.status >= 400:
                    raise Exception(f'Authentication response {resp.status}: {raw}')

                data = json.loads(raw)
                access_token = data['access_token']

        self.connection = websockets.connect(
            urljoin(f'{self.ws_scheme}{self.api_host}', '/ws/v1/queue-status/'),
            extra_headers={'AUTHORIZATION': f'Bearer {access_token}'}
        )
        return await self.connection.__aenter__()

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self.connection.__aexit__(exc_type, exc_value, traceback)

    def __await__(self):
        return self.connection.__await__()


async def next_msg(socket):
    """
    Collects messages from the websocket forever until the connection is closed
    or the program is stopped

    :param socket: The socket ot process

    :return: An iterable of websocket messages
    """
    while msg := await socket.recv():
        try:
            yield json.loads(msg)
        except ClientError:
            break


async def start_docker_container(queue: SocketQueueEntry, network: str, broker_url: str, config: ControllerConfig):
    """
    Spins up a new container to process tasks. The spun up container will be set to process
    the required queue, point at the correct broker and load the environment variables and
    volumes from the config.

    :param queue: The queue for the worker to monitor
    :param network: The network to attach the container to
    :param broker_url: The url of the broker
    :param config: The config loaded at application start
    """
    image_spec = config[queue['name']]

    container_name = f'{image_spec["image"].replace(":", "_").replace("/", "_")}_{uuid4().hex}'

    env_str = ' '.join(f'-e {k}="{v}"' for k, v in {**image_spec.get('env', {}), 'OASIS_WORKER_BROKER_URL': broker_url}.items())
    vol_str = ' '.join(f'-v "{k}:{v}"' for k, v in image_spec.get('volumes', {}).items())

    print(f'Starting container: {image_spec["image"]}')
    await asyncio.create_subprocess_shell(
        f'docker run -d {env_str} {vol_str} --name {container_name} --network {network} {image_spec["image"]} -c 1',
        stdout=asyncio.subprocess.DEVNULL,
    )

    state.setdefault(queue['name'], []).append(container_name)


async def stop_docker_container(queue: SocketQueueEntry):
    """
    Takes the first container for the given queue and stops it.

    :param queue: The queue to process
    """
    container_id = state[queue['name']].pop()
    print(f'Stopping container: {container_id}')
    await asyncio.create_subprocess_shell(
        f'docker stop {container_id}',
        stdout=asyncio.subprocess.DEVNULL,
    )


async def handle_msg(msg: SocketMessage, network: str, broker_url: str, config: ControllerConfig):
    """
    Processes a message sent from the web socket

    :param msg: The message content
    :param network: The network to attach the containers to
    :param broker_url: The url of the broker to point the containers at
    :param config: The config loaded at application start
    """
    content: List[SocketContentEntry] = msg['content']

    for entry in content:
        queue = entry['queue']

        # if the name is not in the config its not handled by this controller so skip it
        if queue['name'] not in config:
            print(f'Skipping queue {queue["name"]} as it\'s not in the config')
            continue

        current_container_count = len(state.get(queue['name'], []))
        print(f'Processing containers for queue "{queue["name"]}", {queue["pending_count"]} tasks pending, {queue["queued_count"]} tasks queued, current num processing containers {current_container_count}')

        # if there are more tasks in the queue than we have workers make a new worker
        if current_container_count < queue['queued_count']:
            for i in range(queue['queued_count'] - current_container_count):
                await start_docker_container(queue, network, broker_url, config)

        # if there are more tasks than currently pending and queued kill some (we use
        # pending + queued here so that we dont kill single workers when tasks run serially)
        if current_container_count > queue['pending_count'] + queue['queued_count']:
            for i in range(current_container_count - (queue['pending_count'] + queue['queued_count'])):
                await stop_docker_container(queue)


async def handle_messages(args, config: ControllerConfig):
    """
    Connects to the websocket and handles all the messages from the websocket.
    If there is ever a connection issue, the process waits for 60 seconds and
    retries the connection.

    :param args: the command line arguments
    :param config: The config loaded at application start
    """
    try:
        async with Connection(args.api_host, args.username, args.password, secure=args.secure) as socket:
            async for msg in next_msg(socket):
                await handle_msg(msg, args.network, args.broker, config)
    except ClientError:
        print(f'Connection to {args.api_host} failed, retrying in 60 seconds...')
        await asyncio.sleep(60)


def load_config(config_path: str) -> Dict[str, ContainerConfig]:
    """
    Loads the config interpolaring and environment varabled in the env
    and volumes sections

    :param config_path: The path to the config file
    :return: THe interpolated config
    """
    with open(config_path) as f:
        config: Dict[str, ContainerConfig] = json.load(f)

        for queue_config in config.values():
            queue_config['env'] = {k: os.path.expandvars(v) for k, v in queue_config.get('env', {}).items()}
            queue_config['volumes'] = {os.path.expandvars(k): os.path.expandvars(v) for k, v in queue_config.get('volumes', {}).items()}

    return config


def main():
    args = parse_args()
    config = load_config(args.config)
    asyncio.get_event_loop().run_until_complete(handle_messages(args, config))


if __name__ == '__main__':
    main()
