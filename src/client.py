from concurrent import futures
import logging
import os, sys
import random

sys.path.append("../protos")

import grpc
import server_pb2_grpc, messages_pb2, client_pb2_grpc

from mafia import Actions

class Client(client_pb2_grpc.ClientServicer):
    def __init__(self, address):
        self.server_stub = None
        self.address = address
        self.name = None
        self.connected_players = []
    
    def link_to_server(self, stub):
        self.server_stub = stub
        mes = messages_pb2.RegisterMessage()
        mes.address = self.address
        answer = self.server_stub.Register(mes)
        if answer.status != messages_pb2.RegisterResult.Status.OK:
            #logging.info("Got registration status " + str(answer.status))
            #logging.info("Something is wrong, exiting")
            exit(1)
        else:
            self.name = answer.name
            self.connected_players = answer.users
            #logging.info("Successfully registered at the server as " + answer.name)
            #logging.info(f"Currently connected players (apart from me, {self.name}), are: {','.join(self.connected_players)}")
    
    def NotifyJoin(self, request, context):
        self.connected_players.append(request.name)
        #logging.info("Welcome, " + request.name)
        #logging.info(f"Currently connected players (apart from me, {self.name}), are: {','.join(self.connected_players)}")
        return messages_pb2.NotifyJoinResponse()
    
    def NotifyLeave(self, request, context):
        if request.name in self.connected_players:
            self.connected_players.remove(request.name)
        #logging.info("Goodbye, " + request.name)
        #logging.info(f"Currently connected players (apart from me, {self.name}), are: {','.join(self.connected_players)}")
        return messages_pb2.NotifyLeaveResponse()

    def GameNotify(self, request, context):
        #logging.info(f"Got {request.type} notification from server: {request.text}")
        return messages_pb2.GameNotifyResponse()
    
    def human_readable_action(action):
        return f"({Actions(action.type).name} {action.arg})"

    def GiveActionOptions(self, request, context):
        # I could make this a pretty rpc call that returns the actions, however, that requires a quick answer (0.2 seconds timeout)
        # A bot could make a decision this fast, but a human could not. Thus I make a separate rpc to set the choice in order to
        # preserve the possibility to let humans play this game
        options = list(request.actions)

        #logging.info(f"My options are: {[Client.human_readable_action(x) for x in options]}")
        option = random.choice(options)
        #logging.info(f"I pick: {Client.human_readable_action(option)}")

        action_mes = messages_pb2.TakeActionMessage()
        action_mes.address = self.address
        action_mes.action.CopyFrom(option)
        result = self.server_stub.TakeAction(action_mes)
        #logging.info(f"Status is {str(result.status)}")

        return messages_pb2.ActionOptionsResponse()

    def Ping(self, request, context):
        return request


def serve():
    # time.sleep(random.randint(1, 5))
    address = "0.0.0.0:" + os.environ.get('CLIENT_PORT', '51076')

    address_for_server = os.environ.get('CLIENT_ADDRESS', address)

    server_address = os.environ.get('SERVER_ADDRESS', '51075')
    channel = grpc.insecure_channel(server_address)
    stub = server_pb2_grpc.ServerStub(channel)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    client_instance = Client(address_for_server)
    client_pb2_grpc.add_ClientServicer_to_server(client_instance, server)
    server.add_insecure_port(address)
    server.start()
    #logging.info("Started client at address " + address)

    client_instance.link_to_server(stub)

    server.wait_for_termination();


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    serve()
