from concurrent import futures
from threading import Lock
import logging
import random
import os, sys
import time

sys.path.append("../protos")

import grpc
import server_pb2_grpc, messages_pb2, client_pb2_grpc

TIMEOUT = 0.2
unused_names = {"IronGolem1543", "EpicWinner", "DoctorWho666", "grpc_master", "CreativeName1234", "LordVoldemort", "Placeholder133"}
connected_users = dict()
connected_names = set()


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

class Server(server_pb2_grpc.ServerServicer):
    def __init__(self):
        self.remove_queue = []
        self.remove_queue_lock = Lock()
        self.registration_lock = Lock()

    def Register(self, request, context):
        answer = messages_pb2.RegisterResult()

        if request.address in connected_users:
            answer.status = messages_pb2.RegisterResult.Status.AlreadyRegistered
        else:

            with self.registration_lock:
                name = random.choice(list(unused_names))
                if request.HasField("name"):
                    if request.name not in connected_names:
                        name = request.name
                
                answer.status = messages_pb2.RegisterResult.Status.OK
                answer.name = name
                answer.users.extend(list(connected_names))

                unused_names.discard(name)
                connected_names.add(name)
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

        return answer
    
    def Leave(self, request, context):
        with self.remove_queue_lock:
            self.remove_queue.append(request.address)
        return messages_pb2.LeaveResponse()
    
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
                connected_names.remove(user.name)
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

def serve():
    address = "0.0.0.0:" + os.environ.get('SERVER_PORT', '51075')
    server_instance = Server()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    server_pb2_grpc.add_ServerServicer_to_server(server_instance, server)
    server.add_insecure_port(address)
    server.start()
    logging.info("Started server at address " + address)
    
    while True:
        server_instance.ping()
        server_instance.remove_users()
        time.sleep(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    serve()
