from config import roles_config, Role
from random import shuffle
from threading import Lock
from enum import Enum
from collections import deque
import time


class PlayerState:
    def __init__(self, name):
        self.name = name
        self.role = None
        self.alive = None

class States(Enum):
    Night = 0
    Day = 1

class Actions(Enum):
    Kill = 1 # Mafia kills a player at night
    Vote = 2 # Vote for a player during the day
    Check = 3 # Police check a player at night
    Sleep = 4 # The day is over
    Wake = 5 # The night is over

class Notification(Enum):
    Killed = 1 # Someone was killed
    Voted = 2 # Someone was voted out
    ChangeState = 3 # Day or Night started
    GameOver = 4 # The game is over
    GameStarts = 5 # Beginning of a game

class ExpectedLockException(Exception):
    pass

class GameState:
    def __init__(self):
        self.players = dict()
        self.game_started = False
        self.day = 0
        self.lock = Lock()

        self.state = None # Night/Day
        self.votes = None # For who each player voted
        self.mafia_votes = None # For who each mafia player voted at night
        self.policeman_votes = None # For who each policeman player voted
        self.done = None # Who is done for this day/night
        self.alive_num = None # How many are alive
        self.done_num = None # How many are done

        self.notifications = deque() # Notifications for the server to send to the clients
        self.await_actions = list() # List of people who we need to ask for actions

        self.mafia_won = True

    def add_player(self, name):
        with self.lock:
            if self.game_started or len(self.players) + 1 > max(roles_config.keys()):
                return False
            self.players[name] = PlayerState(name)
            return True
    
    def get_role(self, name):
        with self.lock:
            if not self.game_started:
                return None
            if name not in self.players:
                return None
            return self.players[name].role

    def remove_player(self, name):
        with self.lock:
            if name in self.players:
                self.players.pop(name)

                if self.game_started:
                    self.alive_num -= 1
                    self.check_done()

    def is_ok(self):
        with self.lock:
            return len(self.players) in roles_config

    def start_game(self):
        with self.lock:
            if self.game_started:
                return
            self.start_time = time.time()
            self.game_started = True
            roles = []
            for role, number in roles_config[len(self.players)].items():
                roles += [role] * number
            shuffle(roles)
            cnt = 0
            for key in self.players:
                self.players[key].role = roles[cnt]
                self.players[key].alive = True
                cnt += 1
            self.alive_num = len(self.players)
            self.notifications.append((Notification.GameStarts, "A new mafia game is starting!"))
            self.setup_day()

    # Returns the list of possible actions for the player
    def actions(self, name):
        res = []

        with self.lock:
            if not self.game_started:
                return res

            if name not in self.players:
                return res

            if not self.players[name].alive:
                return res

            if self.state == States.Day:
                res.append((Actions.Sleep,))
                if self.day > 1:
                    for player, state in self.players.items():
                        if player != name and state.alive:
                            res.append((Actions.Vote, player))
            else:
                res.append((Actions.Wake,))

                if self.players[name].role == Role.Mafia:
                    for player, state in self.players.items():
                        if state.role != Role.Mafia and state.alive:
                            res.append((Actions.Kill, player))

                if self.players[name].role == Role.Policeman:
                    for player, state in self.players.items():
                        if state.role != Role.Policeman:
                            res.append((Actions.Check, player))
        return res

    def check_done(self):
        if self.done_num == self.alive_num:
            if self.state == States.Day:
                self.setup_night()
            else:
                self.setup_day()

    def perform_action(self, name, action):
        with self.lock:
            if action[0] == Actions.Sleep or action[0] == Actions.Wake:
                if name not in self.done:
                    self.done.add(name)
                    self.done_num += 1

                self.check_done()
            else:
                if action[0] == Actions.Vote:
                    self.votes[name] = action[1]
                if action[0] == Actions.Kill:
                    self.mafia_votes[name] = action[1]
                if action[0] == Actions.Check:
                    self.policeman_votes[name] = action[1]
                
                self.await_actions.append(name)

    def setup_day(self):
        if not self.lock.locked:
            raise ExpectedLockException

        if self.day != 0:
            killed = GameState.evaluate_vote(self.mafia_votes)
            if killed is not None:
                self.notifications.append((Notification.Voted, "Player " + killed + " was killed by the mafia"))
                self.players[killed].alive = False
                self.alive_num -= 1
            else:
                self.notifications.append((Notification.Voted, "No one was killed by the mafia this night"))

            police_check = GameState.evaluate_vote(self.policeman_votes)
            if police_check is not None:
                self.notifications.append((Notification.Voted, "The player checked by the police is a " + self.players[police_check].role.name))
            else:
                self.notifications.append((Notification.Voted, "The police failed to coordinate this night"))

        if self.check_over():
            return True

        self.state = States.Day
        self.done = set()
        self.day += 1
        self.votes = dict()

        self.done_num = 0

        self.notifications.append((Notification.ChangeState, "Good morning! A new day is starting."))

        for person, state in self.players.items():
            if state.alive:
                self.await_actions.append(person)
    
    def evaluate_vote(votedict):
        # Independent expertise in who won the vote (for any type of voting)
        # Hoping this function will be used for the next elections in Russia
        votes_dict = dict()
        maxvotes = 0
        who = None
        for vote in votedict.values():
            if vote not in votes_dict:
                votes_dict[vote] = 0
            votes_dict[vote] += 1
            if votes_dict[vote] == maxvotes:
                who = None
            if votes_dict[vote] > maxvotes:
                who = vote
                maxvotes = votes_dict[vote]
        return who

    
    def setup_night(self):
        if not self.lock.locked:
            raise ExpectedLockException

        voted_out = GameState.evaluate_vote(self.votes)
        if voted_out is not None:
            self.players[voted_out].alive = False
            self.notifications.append((Notification.Voted, "Player " + voted_out + " was voted out"))
            self.alive_num -= 1
        else:
            self.notifications.append((Notification.Voted, "No one was voted out"))

        if self.check_over():
            return True

        self.done = set()
        self.done_num = 0
        self.mafia_votes = dict()
        self.policeman_votes = dict()
        self.state = States.Night
        self.notifications.append((Notification.ChangeState, "The day is over, night is starting."))

        for person, state in self.players.items():
            if state.alive:
                self.await_actions.append(person)
    
    def check_over(self):
        if not self.lock.locked:
            raise ExpectedLockException
        mafia_alive = 0
        for person, state in self.players.items():
            if state.alive and state.role == Role.Mafia:
                mafia_alive += 1
        
        if mafia_alive == 0:
            self.notifications.append((Notification.GameOver, "Civilians win!"))
            self.mafia_won = False
            return True
        if mafia_alive != 0 and mafia_alive * 2 >= self.alive_num:
            self.notifications.append((Notification.GameOver, "Mafia wins!"))
            self.mafia_won = True
            return True
        return False
    
    def take_notification(self):
        with self.lock:
            if self.notifications:
                return self.notifications.popleft()
    
    def take_await_actions(self):
        with self.lock:
            if self.await_actions:
                return self.await_actions.pop()
    
    def process_message(self, name):
        with self.lock:
            if not self.game_started:
                return ([player.name for player in self.players.values()], "(pre-game chat)")
            if not self.players[name].alive:
                return ([], "Dead people cannot send messages")
            if self.state == States.Night:
                if self.players[name].role == Role.Mafia:
                    return ([player.name for player in self.players.values() if player.role == Role.Mafia], "(in mafia chat)")
                else:
                    return ([], "Only mafia can message at night")
            else:
                return ([player.name for player in self.players.values()], "(main chat)")