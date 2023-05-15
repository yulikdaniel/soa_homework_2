from concurrent import futures
from threading import Lock
import logging
import random
import os, sys
import time

sys.path.append("../protos")

import grpc
import server_pb2_grpc, messages_pb2, client_pb2_grpc

from mafia import GameState, Notification, Actions

TIMEOUT = 0.2
unused_names = {"IronGolem1543", "EpicWinner", "DoctorWho666", "grpc_master", "CreativeName1234", "LordVoldemort", "Placeholder133"}
connected_users = dict()
address_by_name = dict()


class RemoteClient:
    def __init__(self, address, name):
        self.address = address
        self.name = name
        self.stub = client_pb2_grpc.ClientStub(grpc.insecure_channel(self.address))

    def NotifyNewPerson(self, name, address):
        mes = messages_pb2.JoinNotification()
        mes.name = name
        try:
            self.stub.NotifyJoin(mes, timeout=TIMEOUT)
            return True
        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.DEADLINE_EXCEEDED or rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                return False
            raise rpc_error
    
    def NotifyPersonLeave(self, name):
        mes = messages_pb2.LeaveNotification()
        mes.name = name
        try:
            self.stub.NotifyLeave(mes, timeout=TIMEOUT)
            return True
        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.DEADLINE_EXCEEDED or rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                return False
            raise rpc_error
    
    def Ping(self):
        try:
            self.stub.Ping(messages_pb2.PingMessage(), timeout=TIMEOUT)
            return True
        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.DEADLINE_EXCEEDED or rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                return False
            raise rpc_error
    
    def game_notification(self, notification):
        mes = messages_pb2.GameNotification()
        mes.type = str(notification[0])
        mes.text = notification[1]
        try:
            self.stub.GameNotify(mes, timeout=TIMEOUT)
        except grpc.RpcError as rpc_error:
            if rpc_error.code() != grpc.StatusCode.DEADLINE_EXCEEDED and rpc_error.code() != grpc.StatusCode.UNAVAILABLE:
               raise rpc_error

    def give_options(self, options):
        mes = messages_pb2.ActionOptions()
        for option in options:
            action = mes.actions.add()
            action.type = option[0].value
            if len(option) == 2:
                action.arg = option[1]

        try:
            self.stub.GiveActionOptions(mes, timeout=TIMEOUT)
        except grpc.RpcError as rpc_error:
            if rpc_error.code() != grpc.StatusCode.DEADLINE_EXCEEDED and rpc_error.code() != grpc.StatusCode.UNAVAILABLE:
               raise rpc_error


class Server(server_pb2_grpc.ServerServicer):
    def __init__(self):
        self.remove_queue = []
        self.remove_queue_lock = Lock()
        self.registration_lock = Lock()

        self.game = GameState()

    def Register(self, request, context):
        answer = messages_pb2.RegisterResult()

        if request.address in connected_users:
            answer.status = messages_pb2.RegisterResult.Status.AlreadyRegistered
        else:

            with self.registration_lock:
                name = random.choice(list(unused_names))
                if request.HasField("name"):
                    if request.name not in address_by_name:
                        name = request.name
                
                answer.status = messages_pb2.RegisterResult.Status.OK
                answer.name = name
                answer.users.extend(list(address_by_name.keys()))

                unused_names.discard(name)
                address_by_name[name] = request.address
                connected_users[request.address] = RemoteClient(request.address, name)

            logging.info(name + " at address " + str(request.address) + " has joined the server!!!!")

            small_queue = []
            with self.registration_lock:
                for address in connected_users:
                    if address != request.address:
                        if not connected_users[address].NotifyNewPerson(name, request.address):
                            small_queue.append(address)

            with self.remove_queue_lock:
                self.remove_queue.extend(small_queue)
            
            self.game.add_player(name)
            if self.game.is_ok():
                self.game.start_game()

        return answer

    def Leave(self, request, context):
        with self.remove_queue_lock:
            self.remove_queue.append(request.address)
        return messages_pb2.LeaveResponse()

    def TakeAction(self, request, context):
        address = request.address
        actype = Actions(request.action.type)

        name = connected_users[address].name
        logging.info("Received action " + str(actype) + " from " + name)
        action = (actype, request.action.arg) if request.action.HasField("arg") else (actype,)
        answer = messages_pb2.ActionResult()

        if action in self.game.actions(name):
            answer.status = messages_pb2.ActionResult.Status.OK
            self.game.perform_action(name, action)

            # logging.info("Done action " + str(action) + " from " + name)
        else:
            answer.status = messages_pb2.ActionResult.Status.NotAllowed

        return answer

    def remove_users(self):
        while True:
            with self.remove_queue_lock:
                if len(self.remove_queue) == 0:
                    return
                address = self.remove_queue.pop()
            with self.registration_lock:
                if address not in connected_users:
                    continue
                user = connected_users.pop(address)
                address_by_name.pop(user.name)
                unused_names.add(user.name)

            name = user.name

            logging.info("Say goodbye to " + name)
            for person in connected_users.values():

                if not person.NotifyPersonLeave(name):
                    with self.remove_queue_lock:
                        self.remove_queue.append(person.address)
    
    def ping(self):
        small_queue = []
        with self.registration_lock:
            for address in connected_users:
                if not connected_users[address].Ping():
                    small_queue.append(address)
        with self.remove_queue_lock:
            self.remove_queue.extend(small_queue)
    
    def send_game_notifications(self):
        notification = self.game.take_notification()
        if notification is None:
            return False
        logging.info("Sending everyone " + str(notification))
        with self.registration_lock:
            for address in connected_users:
                connected_users[address].game_notification(notification)

        return True
    
    def send_actions(self):
        waiting_for = self.game.take_await_actions()
        if waiting_for is None:
            return False

        address = address_by_name[waiting_for]
        options = self.game.actions(waiting_for)
        # logging.info("Sending actions to " + waiting_for + " " + str(options))
        connected_users[address].give_options(options)
        # logging.info(f"Done sending actions to {waiting_for}")
        return True
    
    def send_stuff(self):
        while self.send_game_notifications() or self.send_actions():
            pass


def serve():
    address = "0.0.0.0:" + os.environ.get('SERVER_PORT', '51075')
    server_instance = Server()

    executor = futures.ThreadPoolExecutor(max_workers=1)

    server = grpc.server(executor)
    server_pb2_grpc.add_ServerServicer_to_server(server_instance, server)
    server.add_insecure_port(address)
    server.start()
    logging.info("Started server at address " + address)
    
    while True:
        server_instance.ping()
        server_instance.remove_users()
        server_instance.send_stuff()
        time.sleep(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    serve()
