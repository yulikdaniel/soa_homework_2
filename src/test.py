from enum import Enum
import os, sys

sys.path.append("../protos")
import server_pb2_grpc, messages_pb2, client_pb2_grpc


class Actions(Enum):
    Kill = 0 # Mafia kills a player at night
    Vote = 1 # Vote for a player during the day
    Check = 2 # Police check a player at night
    Sleep = 3 # The day is over
    Wake = 4 # The night is over


# opt = messages_pb2.ActionOptions()
# op = opt.actions.add()
# op.type = messages_pb2.Action.Actions.Kill
# op.arg = "hello"

print(Actions.Kill.name)