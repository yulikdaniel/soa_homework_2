from enum import Enum

class Role(Enum):
    Civilian = 1
    Mafia = 2
    Policeman = 3

# Amount of people: role distribution
roles_config = {4: {Role.Civilian: 2, Role.Mafia: 1, Role.Policeman: 1},
                5: {Role.Civilian: 3, Role.Mafia: 1, Role.Policeman: 1},
                6: {Role.Civilian: 3, Role.Mafia: 2, Role.Policeman: 1},
                # 7: {Role.Civilian: 4, Role.Mafia: 2, Role.Policeman: 1},
                # 8: {Role.Civilian: 4, Role.Mafia: 3, Role.Policeman: 1}
                }