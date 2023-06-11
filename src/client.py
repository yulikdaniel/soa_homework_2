from concurrent import futures
import logging
import os, sys
import random
import pika
import threading
from time import sleep

sys.path.append("../protos")

import grpc
import server_pb2_grpc, messages_pb2, client_pb2_grpc

from mafia import Actions

def generate_message():
    return f'''{random.choice(["This", "The current", "The aforementioned", "The ongoing"])} game is {random.choice(["marvelous", "fascinating", "oustanding", "exceeding all expectations"])}{random.choice(["?", "!", ".", "?!", "..."])}'''

class Client(client_pb2_grpc.ClientServicer):
    def __init__(self, address, name):
        self.server_stub = None
        self.address = address
        self.name = name
        self.connected_players = []

        # Handle incoming messages
        while True:
            try:
                connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitMQService"))
                channel = connection.channel()
                channel.queue_declare(queue=str(self.address))
                channel.basic_consume(queue=str(self.address), on_message_callback=Client.MessageCallback, auto_ack=True)
                threading.Thread(target=lambda:channel.start_consuming()).start()
                break
            except:
                logging.info("Waiting for rabbitmq server...")
                sleep(3)

    def link_to_server(self, stub):
        self.server_stub = stub

        mes = messages_pb2.RegisterMessage()
        mes.address = self.address

        if self.name is not None:
            mes.name = self.name

        answer = self.server_stub.Register(mes)

        if answer.status != messages_pb2.RegisterResult.Status.OK:
            logger.info("Got registration status " + str(answer.status))
            logger.info("Something is wrong, exiting")
            exit(1)
        else:
            self.name = answer.name
            logger.info("Successfully registered at the server as " + answer.name)
            logger.info(f"Currently connected players (apart from me, {self.name}), are: {','.join(answer.users)}")
    
    def NotifyJoin(self, request, context):
        self.connected_players.append(request.name)
        logger.info("Welcome, " + request.name)
        logger.info(f"Currently connected players (apart from me, {self.name}), are: {','.join(self.connected_players)}")
        self.MaybeSendMessage()
        return messages_pb2.NotifyJoinResponse()
    
    def NotifyLeave(self, request, context):
        if request.name in self.connected_players:
            self.connected_players.remove(request.name)
        logger.info("Goodbye, " + request.name)
        logger.info(f"Currently connected players (apart from me, {self.name}), are: {','.join(self.connected_players)}")
        self.MaybeSendMessage()
        return messages_pb2.NotifyLeaveResponse()

    def GameNotify(self, request, context):
        logger.info(f"Got {request.type} notification from server: {request.text}")
        self.MaybeSendMessage()
        return messages_pb2.GameNotifyResponse()
    
    def human_readable_action(action):
        return f"({Actions(action.type).name} {action.arg})"

    def GiveActionOptions(self, request, context):
        # I could make this a pretty rpc call that returns the actions, however, that requires a quick answer (0.2 seconds timeout)
        # A bot could make a decision this fast, but a human could not. Thus I make a separate rpc to set the choice in order to
        # preserve the possibility to let humans play this game
        options = list(request.actions)

        logger.info(f"My options are: {[Client.human_readable_action(x) for x in options]}")
        option = random.choice(options)
        logger.info(f"I pick: {Client.human_readable_action(option)}")

        action_mes = messages_pb2.TakeActionMessage()
        action_mes.address = self.address
        action_mes.action.CopyFrom(option)
        result = self.server_stub.TakeAction(action_mes)
        logger.info(f"Status is {str(result.status)}")

        self.MaybeSendMessage()

        return messages_pb2.ActionOptionsResponse()

    def Ping(self, request, context):
        self.MaybeSendMessage()
        return request
    
    def SendRole(self, request, context):
        logger.info(f"My role is {request.role}")
        self.MaybeSendMessage()
        return messages_pb2.SendRoleResponse()
    
    def NewGame(self, request, context):
        self.connected_players = request.users
        logger.info(f"I entered session ({request.game_id}). With players {', '.join(self.connected_players)} and me, {self.name}")
        self.MaybeSendMessage()
        return messages_pb2.NewGameResponse()
    
    def MessageCallback(channel, method, properties, body):
        logger.info(f"Got chat message: {body.decode()}")
    
    def MaybeSendMessage(self):
        if random.randint(0, 20) == 0:
            mes = generate_message()
            logger.info(f"Sending message to server: {mes}")
            connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitMQService"))
            channel = connection.channel()
            channel.queue_declare(str(self.address) + "_out")
            channel.basic_publish(exchange='', routing_key=str(self.address) + "_out", body=mes.encode())
            connection.close()

def serve():
    name = os.getenv("USERNAME")

    address = "0.0.0.0:" + os.environ.get('CLIENT_PORT', '51076')

    address_for_server = os.environ.get('CLIENT_ADDRESS', address)

    server_address = os.environ.get('SERVER_ADDRESS', '51075')
    channel = grpc.insecure_channel(server_address)
    stub = server_pb2_grpc.ServerStub(channel)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    client_instance = Client(address_for_server, name)
    client_pb2_grpc.add_ClientServicer_to_server(client_instance, server)
    server.add_insecure_port(address)
    server.start()
    logger.info("Started client at address " + address)

    client_instance.link_to_server(stub)

    server.wait_for_termination();


if __name__ == '__main__':
    logger = logging.getLogger("Client")
    logger.setLevel(level=logging.DEBUG)
    logger.info("Trying to start client")
    serve()
