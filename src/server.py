from concurrent import futures
import logging
import random
import os, sys
import time
import requests
from config import Role
import pika
import threading

sys.path.append("../protos")

import grpc
import server_pb2_grpc, messages_pb2, client_pb2_grpc

from mafia import GameState, Notification, Actions

TIMEOUT = 0.2
TIME_BETWEEN_GAMES = 5


def random_email(name):
    return name + "@" + random.choice(["gmail.com", "yandex.ru", "edu.hse.ru", "myself.com", "musician.org", "workmail.com"])


class RemoteClient:
    def __init__(self, address, name):
        self.address = address
        self.name = name
        self.stub = client_pb2_grpc.ClientStub(grpc.insecure_channel(self.address))
        self.game_id = None
        
        while True:
            try:
                connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitMQService"))
                channel = connection.channel()
                channel.queue_declare(queue=str(self.address) + "_out")
                channel.basic_consume(queue=str(self.address) + "_out", on_message_callback=lambda *args: server_instance.on_client_message(*args, self.address), auto_ack=True)
                threading.Thread(target=lambda:channel.start_consuming()).start()
                break
            except:
                time.sleep(3)
                logger.info("Waiting for rabbitmq server to start")

    def NotifyNewPerson(self, name):
        mes = messages_pb2.JoinNotification()
        mes.name = name
        try:
            self.stub.NotifyJoin(mes, timeout=TIMEOUT)
            return True
        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.DEADLINE_EXCEEDED or rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                logger.info("Failed to answer notify new person")
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
                logger.info("Failed to answer notify person leave")
                return False
            raise rpc_error
    
    def Ping(self):
        try:
            self.stub.Ping(messages_pb2.PingMessage(), timeout=TIMEOUT)
            return True
        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.DEADLINE_EXCEEDED or rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                logger.info("Failed to answer ping")
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
    
    def send_role(self, role):
        mes = messages_pb2.RoleInfo()
        mes.role = str(role)

        try:
            self.stub.SendRole(mes, timeout=TIMEOUT)
        except grpc.RpcError as rpc_error:
            if rpc_error.code() != grpc.StatusCode.DEADLINE_EXCEEDED and rpc_error.code() != grpc.StatusCode.UNAVAILABLE:
               raise rpc_error

    def new_game(self, players, game_id):
        mes = messages_pb2.NewGameDetails()
        mes.users.extend(players)
        mes.game_id = game_id

        try:
            self.stub.NewGame(mes, timeout=TIMEOUT)
        except grpc.RpcError as rpc_error:
            if rpc_error.code() != grpc.StatusCode.DEADLINE_EXCEEDED and rpc_error.code() != grpc.StatusCode.UNAVAILABLE:
               raise rpc_error
    
    def chat_message(self, message):
        connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitMQService"))
        channel = connection.channel()
        channel.queue_declare(str(self.address))
        channel.basic_publish(exchange='', routing_key=str(self.address), body=message.encode())
        connection.close()


class Server(server_pb2_grpc.ServerServicer):
    def __init__(self, db_server):
        self.remove_queue = []
        self.remove_queue_lock = threading.Lock()
        self.registration_lock = threading.Lock()
        self.last_checkpoint = time.time()

        self.games = dict()
        self.unique_game_id = 0

        self.unused_names = {"IronGolem1543", "EpicWinner", "DoctorWho666", "grpc_master", "CreativeName1234", "LordVoldemort", "Placeholder133", "ConcurrencyRules", "IAmDoneWithThisHomework", "SpaceBar"}
        self.connected_users = dict()
        self.address_by_name = dict()
        self.db_server = db_server

    def Register(self, request, context):
        answer = messages_pb2.RegisterResult()

        if request.address in self.connected_users:
            answer.status = messages_pb2.RegisterResult.Status.AlreadyRegistered
        else:

            with self.registration_lock:
                name = None
                if request.HasField("name"):
                    if request.name not in self.address_by_name:
                        name = request.name
                if name is None:
                    name = random.choice(list(self.unused_names))

                answer.status = messages_pb2.RegisterResult.Status.OK
                answer.name = name
                answer.users.extend(list(self.address_by_name.keys()))

                self.unused_names.discard(name)
                self.address_by_name[name] = request.address
                self.connected_users[request.address] = RemoteClient(request.address, name)

            if self.db_server:
                requests.post(self.db_server + f"/users/{name}", json={"email": random_email(name), "age": random.randint(0, 154)})

        return answer

    def PickGame(self, name):
        chosen = None
        for game_id, game in self.games.items():
            if game.add_player(name):
                chosen = game_id
                break
        else: # All games are full or started
            self.unique_game_id += 1
            self.games[self.unique_game_id] = GameState()
            self.games[self.unique_game_id].add_player(name) # This must return true
            chosen = self.unique_game_id

        self.connected_users[self.address_by_name[name]].new_game([player.name for player in self.connected_users.values() if player.game_id == chosen], chosen)
        self.connected_users[self.address_by_name[name]].game_id = chosen

        logger.info(name + " has joined game " + str(chosen))

        small_queue = []
        for address, state in self.connected_users.items():
            if state.name != name and state.game_id == chosen:
                if not state.NotifyNewPerson(name):
                    small_queue.append(address)

        with self.remove_queue_lock:
            self.remove_queue.extend(small_queue)

        return self.unique_game_id

    def Leave(self, request, context):
        with self.remove_queue_lock:
            self.remove_queue.append(request.address)
        return messages_pb2.LeaveResponse()

    def TakeAction(self, request, context):
        address = request.address

        answer = messages_pb2.ActionResult()

        if address not in self.connected_users or self.connected_users[address].game_id is None:
            answer.status = messages_pb2.ActionResult.Status.NotAllowed
            return answer

        actype = Actions(request.action.type)

        name = self.connected_users[address].name
        logger.info(f"Received action {actype} {request.action.arg} from {name}")
        action = (actype, request.action.arg) if request.action.HasField("arg") else (actype,)

        if action in self.games[self.connected_users[address].game_id].actions(name):
            answer.status = messages_pb2.ActionResult.Status.OK
            self.games[self.connected_users[address].game_id].perform_action(name, action)
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
                if address not in self.connected_users:
                    continue
                user = self.connected_users.pop(address)
                self.address_by_name.pop(user.name)
                self.unused_names.add(user.name)

                if user.game_id is not None:
                    self.games[user.game_id].remove_player(user.name)

                name = user.name
                small_queue = []
                logger.info("Say goodbye to " + name + " they left the server")

                if user.game_id is not None:
                    for person in self.connected_users.values():
                        if person.game_id == user.game_id:
                            if not person.NotifyPersonLeave(name):
                                small_queue.append(person.address)

            with self.remove_queue_lock:
                self.remove_queue.extend(small_queue)
    
    def ping(self):
        small_queue = []
        with self.registration_lock:
            for address in self.connected_users:
                if not self.connected_users[address].Ping():
                    small_queue.append(address)
        with self.remove_queue_lock:
            self.remove_queue.extend(small_queue)
    
    def send_game_notifications(self, game_id):
        with self.registration_lock:
            if game_id not in self.games:
                return False
            notification = self.games[game_id].take_notification()

        if notification is None:
            return False

        logger.info("Sending everyone in game" + str(game_id) + " " + str(notification))
        with self.registration_lock:
            for state in self.connected_users.values():
                if state.game_id == game_id:
                    state.game_notification(notification)

        if notification[0] == Notification.GameOver:
            with self.registration_lock:
                game = self.games.pop(game_id)
                for state in self.connected_users.values():
                    if state.game_id == game_id:
                        state.game_id = None

            if self.db_server:
                now = time.time()
                for player in game.players.values():
                    requests.put(self.db_server + f"/users/add/{player.name}",
                                  json={"played" : 1, "wins" : int(game.mafia_won == (player.role == Role.Mafia)), "ingame" : round(now - game.start_time, 3)})

        if notification[0] == Notification.GameStarts:
            with self.registration_lock:
                for state in self.connected_users.values():
                    if state.game_id == game_id:
                        state.send_role(self.games[game_id].get_role(state.name))

        return True

    def send_actions(self, game_id):
        with self.registration_lock:
            if game_id not in self.games:
                return False

            waiting_for = self.games[game_id].take_await_actions()
            if waiting_for is None:
                return False

        with self.registration_lock:
            if waiting_for not in self.address_by_name:
                return False

            address = self.address_by_name[waiting_for]
            options = self.games[game_id].actions(waiting_for)
            self.connected_users[address].give_options(options)

        return True

    def send_stuff(self):
        served = set()
        while True:
            chosen = None
            with self.registration_lock:
                for game_id in self.games:
                    if game_id not in served:
                        chosen = game_id
                        break

            if chosen is not None:
                served.add(game_id)
                while (self.send_game_notifications(chosen) or self.send_actions(chosen)):
                    pass
            else:
                break
    
    def pick_games(self):
        with self.registration_lock:
            for state in self.connected_users.values():
                if state.game_id is None:
                    self.PickGame(state.name)
    
    def attempt_start_game(self):
        if time.time() > self.last_checkpoint + TIME_BETWEEN_GAMES:
            for game_id in self.games:
                if self.games[game_id].is_ok():
                    logger.info("Game " + str(game_id) + " is running...")
                    self.games[game_id].start_game()
                else:
                    logger.info("Game " + str(game_id) + " is still missing players to start...")

            self.last_checkpoint = time.time()
    
    def on_client_message(self, channel, method, properties, body, address):
        with self.registration_lock:
            logger.info(f"Got a message from a client! {body.decode()}")
            player = self.connected_users.get(address)
            if player is not None:
                game_id = player.game_id
                if game_id is None:
                    player.chat_message("SERVER: Cannot send messages while not in game session")
                else:
                    recv, comment = self.games[game_id].process_message(player.name)
                    for name in recv:
                        if name == player.name:
                            continue
                        self.connected_users[self.address_by_name[name]].chat_message(f"{player.name}{comment}: {body.decode()}")
                    if not recv:
                        player.chat_message(f"SERVER: {comment}")

if __name__ == '__main__':
    logger = logging.getLogger("SERVER")
    logger.setLevel(logging.DEBUG)

    db_server = os.environ.get("RESTSERVER_PORT")
    if db_server is not None:
        db_server = "http://" + db_server

    address = "0.0.0.0:" + os.environ.get('SERVER_PORT', '51075')
    server_instance = Server(db_server)

    executor = futures.ThreadPoolExecutor(max_workers=1)

    server = grpc.server(executor)
    server_pb2_grpc.add_ServerServicer_to_server(server_instance, server)
    server.add_insecure_port(address)
    server.start()
    logger.info("Started server at address " + address)

    while True:
        server_instance.ping()
        server_instance.remove_users()
        server_instance.attempt_start_game()
        server_instance.send_stuff()
        server_instance.pick_games()
        time.sleep(1)
