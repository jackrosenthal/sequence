import enum
import functools
import io
import itertools
import random

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "X", "J", "Q", "K", "A"]
SUITS = ["H", "C", "D", "S"]
ALL_CARDS = [f"{rank}{suit}" for rank in RANKS for suit in SUITS] * 2 + ["JJ"]
ONE_EYEDS = ["JS", "JH"]
TWO_EYEDS = ["JC", "JD"]


CORN = object()


class IllegalMove(Exception):
    pass


class GameSetupError(Exception):
    pass


def pretty_card(card):
    if card is CORN:
        return "Corner"
    if card == "JJ":
        return "Joker"
    else:
        card_suit = {
            "H": "♥",
            "C": "♣",
            "D": "♦",
            "S": "♠",
        }[card[-1]]
        card_rank = "10" if card[0] == "X" else card[0]
        return card_rank + card_suit


def unique_cards_by_action(cards):
    cards = set(cards)
    if "JH" in cards:
        cards.discard("JS")
    if "JC" in cards:
        cards.discard("JD")
    return cards


def sort_hand(hand):
    return sorted(
        hand,
        key=lambda card: (
            card == "JJ",
            card in TWO_EYEDS,
            card in ONE_EYEDS,
            "HCDS".find(card[1]),
            "23456789XQKA".find(card[0]),
        ),
    )


class MoveType(enum.Enum):
    PLACE_CHIP = enum.auto()
    REMOVE_CHIP = enum.auto()


def describe_move(move, board):
    card, action, pos = move
    board_card, board_chip = board.getpos(pos)
    if action == MoveType.PLACE_CHIP:
        return f"Play on the {pretty_card(board_card)} at {pos}."
    else:  # action == MoveType.REMOVE_CHIP
        return (
            f"Remove the {board_chip.team}'s chip on the "
            f"{pretty_card(board_card)} at {pos}."
        )


def coord_closeness_to_center(val):
    if val in (4, 5):
        return 5
    if val in (3, 6):
        return 4
    if val in (2, 7):
        return 3
    if val in (1, 8):
        return 2
    return 1


def move_weight_centermost(move):
    card, move_type, pos = move
    pos_x, pos_y = pos
    return min(coord_closeness_to_center(pos_x), coord_closeness_to_center(pos_y))


def sequence_gen_restrict(row_restrict, col_restrict):
    def dec(func):
        @functools.wraps(func)
        def wrapper(pos):
            row, col = pos
            assert row in row_restrict
            assert col in col_restrict
            return func(row, col)

        def iter_inputs():
            for row in row_restrict:
                for col in col_restrict:
                    yield (row, col)

        wrapper.iter_inputs = iter_inputs
        return wrapper

    return dec


@sequence_gen_restrict(range(10), range(6))
def hrsequence(row, column):
    return {(row, c) for c in range(column, column + 5)}


@sequence_gen_restrict(range(6), range(10))
def vdsequence(row, column):
    return {(r, column) for r in range(row, row + 5)}


@sequence_gen_restrict(range(6), range(6))
def ddsequence(row, column):
    return {(row + n, column + n) for n in range(5)}


@sequence_gen_restrict(range(4, 10), range(6))
def dusequence(row, column):
    return {(row - n, column + n) for n in range(5)}


def iter_all_sequences():
    for func in [hrsequence, vdsequence, ddsequence, dusequence]:
        for pos in func.iter_inputs():
            yield func(pos)


def iter_corner_sequences():
    # Top left
    yield hrsequence((0, 0))
    yield vdsequence((0, 0))
    yield ddsequence((0, 0))

    # Top right
    yield hrsequence((0, 5))
    yield vdsequence((0, 9))
    yield dusequence((4, 5))

    # Bottom left
    yield hrsequence((9, 0))
    yield vdsequence((5, 0))
    yield dusequence((9, 0))

    # Bottom right
    yield hrsequence((9, 5))
    yield vdsequence((5, 9))
    yield ddsequence((5, 5))


def iter_pos():
    for row in range(10):
        for col in range(10):
            yield (row, col)


class Chip:
    def __init__(self, team):
        self.team = team
        self._flipped = False

    def flip(self):
        assert not self._flipped
        self._flipped = True

    def is_flipped(self):
        return self._flipped


class Board:
    positions = [
        [CORN, "6D", "7D", "8D", "9D", "XD", "QD", "KD", "AD", CORN],
        ["5D", "3H", "2H", "2S", "3S", "4S", "5S", "6S", "7S", "AC"],
        ["4D", "4H", "KD", "AD", "AC", "KC", "QC", "XC", "8S", "KC"],
        ["3D", "5H", "QD", "QH", "XH", "9H", "8H", "9C", "9S", "QC"],
        ["2D", "6H", "XD", "KH", "3H", "2H", "7H", "8C", "XS", "XC"],
        ["AS", "7H", "9D", "AH", "4H", "5H", "6H", "7C", "QS", "9C"],
        ["KS", "8H", "8D", "2C", "3C", "4C", "5C", "6C", "KS", "8C"],
        ["QS", "9H", "7D", "6D", "5D", "4D", "3D", "2D", "AS", "7C"],
        ["XS", "XH", "QH", "KH", "AH", "2C", "3C", "4C", "5C", "6C"],
        [CORN, "9S", "8S", "7S", "6S", "5S", "4S", "3S", "2S", CORN],
    ]

    def __init__(self, teams):
        self.chips = [[None] * 10 for _ in range(10)]
        self.teams = teams

    def getpos(self, pos):
        """Get a 2-tuple of (card, chip) for a given position."""
        row, column = pos
        assert 0 <= row < 10
        assert 0 <= column < 10
        return (self.positions[row][column], self.chips[row][column])

    def iter_moves(self, card, team):
        def removal_moves():
            for pos in iter_pos():
                _, chip = self.getpos(pos)
                if not chip:
                    continue
                if chip.team is not team and not chip.is_flipped():
                    yield (card, MoveType.REMOVE_CHIP, pos)

        def place_moves():
            for pos in iter_pos():
                pos_card, chip = self.getpos(pos)
                if chip or pos_card is CORN:
                    continue
                if pos_card == card or card in TWO_EYEDS or card == "JJ":
                    yield (card, MoveType.PLACE_CHIP, pos)

        if card in ONE_EYEDS or card == "JJ":
            yield from removal_moves()
        if card not in ONE_EYEDS:
            yield from place_moves()

    def put_chip(self, card, pos, team):
        current_card, current_chip = self.getpos(pos)
        if current_card is CORN:
            raise IllegalMove("Cannot play on the corners.")
        if card in ONE_EYEDS:
            raise IllegalMove("One-eyed jacks cannot be used to play a chip.")
        if current_chip:
            raise IllegalMove("There is already a chip here.")
        if not (card in TWO_EYEDS or card == "JJ") and card != current_card:
            raise IllegalMove(f"The {card} cannot be played on the {current_card}.")
        row, column = pos
        self.chips[row][column] = Chip(team)
        self.update_sequences()

    def remove_chip(self, card, pos, team):
        current_card, current_chip = self.getpos(pos)
        if not current_chip:
            raise IllegalMove("There is no chip here to remove.")
        assert current_card is not CORN
        if current_chip.is_flipped():
            raise IllegalMove("You cannot remove chips in a sequence.")
        if current_chip.team is team:
            raise IllegalMove("You cannot remove your own chips.")
        if card != "JJ" and card not in ONE_EYEDS:
            raise IllegalMove(f"The {card} cannot be used to remove chips.")
        row, column = pos
        self.chips[row][column] = None

    def iter_sequences(
        self,
        exclude_corner_extensions=False,
        exclude_impossible_for_team=None,
        one_eyeds_to_make_possible=0,
        includes_positions=(),
    ):
        """Iterate thru all possible sequences as sets of positions."""

        def non_corner_extension(seq):
            for cseq in iter_corner_sequences():
                if len(seq & cseq) == 4:
                    return False
            return True

        def possible(seq):
            one_eyeds_have = one_eyeds_to_make_possible
            for pos in seq:
                card, chip = self.getpos(pos)
                if chip and chip.team is not exclude_impossible_for_team:
                    if one_eyeds_have > 0 and not chip.is_flipped():
                        one_eyeds_have -= 1
                        continue
                    return False
            return True

        def position_filter(seq):
            for pos in includes_positions:
                if pos not in seq:
                    return False
            return True

        filters = []
        if exclude_corner_extensions:
            filters.append(non_corner_extension)
        if exclude_impossible_for_team:
            filters.append(possible)
        if includes_positions:
            filters.append(position_filter)

        for seq in iter_all_sequences():
            for func in filters:
                if not func(seq):
                    break
            else:
                yield seq

    def update_sequences(self):
        for seq in self.iter_sequences():
            winning_team = None
            for pos in seq:
                card, chip = self.getpos(pos)
                if card is CORN:
                    continue
                if not chip:
                    break
                if winning_team and winning_team is not chip.team:
                    break
                winning_team = chip.team
            else:
                # The sequence has a winner!
                for pos in seq:
                    card, chip = self.getpos(pos)
                    if chip and not chip.is_flipped():
                        chip.flip()

    def get_winning_sequences_for_team(self, team):
        winning_sequences = []
        for seq in self.iter_sequences():
            if any(len(w & seq) > 1 for w in winning_sequences):
                continue
            for pos in seq:
                card, chip = self.getpos(pos)
                if card is CORN:
                    continue
                if not chip or chip.team is not team or not chip.is_flipped():
                    break
            else:
                winning_sequences.append(seq)
        return winning_sequences

    def __str__(self):
        output = io.StringIO()
        output.write("   ")
        for col in range(10):
            output.write(f"{col}  ")
        output.write("\n")
        for row in range(10):
            output.write(f"{row}  ")
            for col in range(10):
                card, chip = self.getpos((row, col))
                if card is CORN:
                    output.write("%%")
                elif not chip:
                    output.write(card)
                else:
                    if chip.is_flipped():
                        output.write("\033[1m")
                    output.write(
                        "\033[{}m".format(
                            {
                                TeamColor.BLUE: 34,
                                TeamColor.GREEN: 32,
                                TeamColor.RED: 31,
                            }[chip.team.color]
                        )
                    )
                    output.write(card)
                    output.write("\033[0m")
                output.write(" ")
            output.write("\n")
        return output.getvalue()


class TeamColor(enum.Enum):
    BLUE = enum.auto()
    GREEN = enum.auto()
    RED = enum.auto()


class Team:
    def __init__(self, color):
        self.color = color
        self.players = []

    def __str__(self):
        return f"{self.color.name} Team".title()

    def add_player(self, *args, **kwargs):
        kwargs.setdefault("team", self)
        player = Player(*args, **kwargs)
        self.players.append(player)
        return player


class Player:
    def __init__(self, name, team, strategy, ui):
        self.name = name
        self.team = team
        self.strategy = strategy
        self.hand = []
        self.ui = ui

    def __str__(self):
        return f"{self.name} ({self.team})"


def play_game(teams, ui):
    keep_playing = False
    sequences = {}

    if len(teams) == 2:
        sequences_to_win = 2
    elif len(teams) == 3:
        sequences_to_win = 1
    else:
        raise GameSetupError("Sequence can only be played with 2 or 3 teams.")

    team_size = None
    for team in teams:
        if team_size is None:
            team_size = len(team.players)
        if len(team.players) != team_size:
            raise GameSetupError("All teams must have the same size.")

    if team_size == 0:
        raise GameSetupError("No players!")
    if len(teams) == 2 and team_size > 5:
        raise GameSetupError("For 2 teams, the maximum team size is 5 players.")
    if len(teams) == 3 and team_size > 4:
        raise GameSetupError("For 3 teams, the maximum team size is 4 players.")

    players = []
    for group in zip(*(team.players for team in teams)):
        players += group

    if len(set(players)) != len(players):
        raise GameSetupError("The set of players on each team must be disjoint.")

    cards_in_hand = {
        2: 7,
        3: 6,
        4: 6,
        6: 5,
        8: 4,
        9: 4,
        10: 3,
        12: 3,
    }[len(players)]

    board = Board(teams)

    for player in players:
        player.strategy.set_game_parameters(
            player, board, sequences_to_win, cards_in_hand
        )

    # Deal the cards.
    deck = list(ALL_CARDS)
    random.shuffle(deck)
    for player in players:
        for _ in range(cards_in_hand):
            player.hand.append(deck.pop())

    for player in itertools.cycle(players):
        if not player.hand:
            # Ending condition for keep_playing mode.
            ui.player_has_empty_hand(player, sequences)
            return max(sequences, key=lambda k: len(sequences[k]))

        ui.notify_turn(player)
        ui.update_board(board)

        # Evaluate any dead cards.
        for card in player.hand:
            if card in ONE_EYEDS:
                continue
            it = board.iter_moves(card, player.team)
            try:
                next(it)
            except StopIteration:
                # Card is dead!
                if player.strategy.query_dead_card(card):
                    # They want it gone.
                    ui.notify_dead_card_discard(player, card)
                    player.hand.remove(card)

                    for notify_player in players:
                        if notify_player is player:
                            continue
                        notify_player.strategy.notify_dead_card_discard(player, card)

                    if deck:
                        card = deck.pop()
                        player.strategy.notify_pickup(card)
                        player.hand.append(card)

        # See what they want to do.
        card, action, pos = player.strategy.query_move()
        player.hand.remove(card)
        if action is MoveType.PLACE_CHIP:
            board.put_chip(card, pos, player.team)
            ui.play_chip(player, card, pos)
        else:
            board_card, board_chip = board.getpos(pos)
            board.remove_chip(card, pos, player.team)
            ui.remove_chip(player, card, board_chip.team, board_card, pos)

        for notify_player in players:
            if notify_player is player:
                continue
            notify_player.strategy.notify_move(player, (card, action, pos))

        # See if their team has won.
        sequences = {team: board.get_winning_sequences_for_team(team) for team in teams}
        winning_sequences = sequences[player.team]

        if len(winning_sequences) >= sequences_to_win and not keep_playing:
            shut_out = True
            for team, seqs in sequences.items():
                if seqs and team is not player.team:
                    shut_out = False
            ui.update_board(board)
            if (
                ui.game_over(player.team, winning_sequences, shut_out=shut_out)
                == "Exit"
            ):
                return player.team
            keep_playing = True

        if deck:
            card = deck.pop()
            player.strategy.notify_pickup(card)
            player.hand.append(card)
