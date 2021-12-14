#!/usr/bin/env python3

import ast
import argparse
import enum
import io
import itertools
import functools
import random
import re

ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "X", "J", "Q", "K", "A"]
suits = ["H", "C", "D", "S"]
all_cards = ["{}{}".format(rank, suit) for rank in ranks for suit in suits] * 2 + ["JJ"]
one_eyeds = ["JS", "JH"]
two_eyeds = ["JC", "JD"]


CORN = object()


class MoveType(enum.Enum):
    PLACE_CHIP = enum.auto()
    REMOVE_CHIP = enum.auto()


def unique_cards_by_action(cards):
    cards = set(cards)
    if "JH" in cards:
        cards.discard("JS")
    if "JC" in cards:
        cards.discard("JD")
    return cards


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


class IllegalMove(Exception):
    pass


class GameSetupError(Exception):
    pass


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
                if pos_card == card or card in two_eyeds or card == "JJ":
                    yield (card, MoveType.PLACE_CHIP, pos)

        if card in one_eyeds or card == "JJ":
            yield from removal_moves()
        if card not in one_eyeds:
            yield from place_moves()

    def put_chip(self, card, pos, team):
        current_card, current_chip = self.getpos(pos)
        if current_card is CORN:
            raise IllegalMove("Cannot play on the corners.")
        if card in one_eyeds:
            raise IllegalMove("One-eyed jacks cannot be used to play a chip.")
        if current_chip:
            raise IllegalMove("There is already a chip here.")
        if not (card in two_eyeds or card == "JJ") and card != current_card:
            raise IllegalMove(
                "The {} cannot be played on the {}.".format(card, current_card)
            )
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
        if card != "JJ" and card not in one_eyeds:
            raise IllegalMove("The {} cannot be used to remove chips.".format(card))
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
            output.write("{}  ".format(col))
        output.write("\n")
        for row in range(10):
            output.write("{}  ".format(row))
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


def sequence_completion(seq, board, team):
    completion = 0
    one_eyeds_required = 0
    shared_chip_encountered = False
    for pos in seq:
        card, chip = board.getpos(pos)
        if card is CORN:
            completion += 1
            continue
        if not chip:
            continue
        if chip.is_flipped():
            if chip.team is team and not shared_chip_encountered:
                shared_chip_encountered = True
                completion += 1
                continue
            else:
                return None, None
        if chip.team is team:
            completion += 1
        else:
            one_eyeds_required += 1
    return completion, one_eyeds_required


class TeamColor(enum.Enum):
    BLUE = enum.auto()
    GREEN = enum.auto()
    RED = enum.auto()


class Team:
    def __init__(self, color):
        self.color = color
        self.players = []

    def __str__(self):
        return "{} Team".format(self.color.name).title()


class Player:
    def __init__(self, name, team, strategy):
        self.name = name
        self.team = team
        self.strategy = strategy
        self.hand = []
        team.players.append(self)

    def __str__(self):
        return "{} ({})".format(self.name, self.team)


class BaseStrategy:
    def set_game_parameters(self, player, board, sequences_to_win, cards_per_player):
        self.player = player
        self.board = board
        self.sequences_to_win = sequences_to_win
        self.cards_per_player = cards_per_player

    def notify_move(self, player, move):
        pass

    def notify_dead_card_discard(self, player, card):
        pass

    def notify_pickup(self, card):
        pass

    def query_dead_card(self, card):
        # By default, assume the strategy wants to discard dead cards.
        return True

    def query_move(self):
        raise NotImplementedError


class RandomStrategy(BaseStrategy):
    def query_move(self):
        moves = [
            move
            for card in self.player.hand
            for move in self.board.iter_moves(card, player.team)
        ]
        return random.choice(moves)


class HumanStrategy(BaseStrategy):
    def notify_pickup(self, card):
        print("[{}] You picked up the {}.".format(self.player, card))

    def query_dead_card(self, card):
        while True:
            answer = input(
                "[{}] You have a dead card ({}) in your hand. "
                "Want to discard it (Y/n)? ".format(self.player, card)
            )
            answer = answer.lower().strip()
            if not answer or answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

    def query_move(self):
        while True:
            hand = sorted(
                self.player.hand,
                key=lambda card: (
                    card == "JJ",
                    card in two_eyeds,
                    card in one_eyeds,
                    "HCDS".find(card[1]),
                    "23456789XQKA".find(card[0]),
                ),
            )
            card = input(
                "[{}] Which card to play ({})? ".format(self.player, ", ".join(hand))
            )
            card = card.upper().strip()
            if card not in self.player.hand:
                print("That card is not in your hand!")
                continue
            moves = list(self.board.iter_moves(card, self.player.team))
            print("How do you want to play it?\n")
            for i, move in enumerate(moves):
                card, action, pos = move
                board_card, board_chip = self.board.getpos(pos)
                if action == MoveType.PLACE_CHIP:
                    print("{:>3}. Play on the {} at {}.".format(i + 1, board_card, pos))
                else:
                    print(
                        "{:>3}. Remove {}'s chip on the {} at {}.".format(
                            i + 1, board_chip.team, board_card, pos
                        )
                    )
            print(
                "{:>3}. Choose a different card to play from your hand.\n".format(
                    len(moves) + 1
                )
            )
            move_choice = input("Your choice? ")
            try:
                move_idx = int(move_choice)
            except ValueError:
                print("Input not valid, expected an integer.")
                continue
            if move_idx == len(moves) + 1:
                continue
            if not (1 <= move_idx <= len(moves)):
                print("Input not valid.")
                continue
            return moves[move_idx - 1]


class WeightedBaseStrategy(BaseStrategy):
    def move_weight(self, move):
        raise NotImplementedError

    def query_move(self):
        return max(
            (
                move
                for card in unique_cards_by_action(self.player.hand)
                for move in self.board.iter_moves(card, self.player.team)
            ),
            key=lambda move: self.move_weight(move),
        )


class SimpleWeightingStrategy(WeightedBaseStrategy):
    DEFAULT_OFFENSE_MULTIPLIERS = (1, 1.1, 2, 4, 10)
    DEFAULT_DEFENSE_MULTIPLIERS = (0.1, 0.15, 0.5, 1.5, 5)
    DEFAULT_ALIGNMENT_MULTIPLIERS = (0, 0.5, 0.75, 2, 3)

    def __init__(
        self,
        offense_multipliers=None,
        defense_multipliers=None,
        alignment_multipliers=None,
        debug_moves=False,
        two_eyed_non_completion_multiplier=0.5,
        two_eyed_multiplier=0.9,
        joker_multiplier=0.8,
    ):
        self.offense_multipliers = (
            offense_multipliers or self.DEFAULT_OFFENSE_MULTIPLIERS
        )
        self.defense_multipliers = (
            defense_multipliers or self.DEFAULT_DEFENSE_MULTIPLIERS
        )
        self.alignment_multipliers = (
            alignment_multipliers or self.DEFAULT_ALIGNMENT_MULTIPLIERS
        )
        self.debug_moves = debug_moves
        self.two_eyed_non_completion_multiplier = two_eyed_non_completion_multiplier
        self.two_eyed_multiplier = two_eyed_multiplier
        self.joker_multiplier = joker_multiplier
        self.cards_played = []

    def _offense_move_weights(self, move):
        num_one_eyeds = sum(
            1 for card in self.player.hand if card in one_eyeds or card == "JJ"
        )
        card, move_type, pos = move
        offense_values = [0] * 5

        for seq in self.board.iter_sequences(
            exclude_corner_extensions=True, includes_positions=(pos,)
        ):
            completion, one_eyeds_required = sequence_completion(
                seq, self.board, self.player.team
            )

            if completion is None:
                continue

            if one_eyeds_required > num_one_eyeds:
                # We don't have enough one-eyeds to complete, don't
                # consider it.
                continue

            # If we are removing a chip, we can consider this to be an
            # offensive move for completing a sequence.  The
            # "completion" is going to be reduced by the number of
            # one-eyeds required, as at least N more turns will be
            # required to complete the sequence.
            if move_type == MoveType.REMOVE_CHIP:
                if one_eyeds_required <= completion:
                    completion -= one_eyeds_required
                else:
                    continue

            offense_values[completion] += 1

        if self.debug_moves:
            print("  OFFENSE={}".format(offense_values))
        return offense_values

    def _defense_move_weights(self, move):
        card, move_type, pos = move
        defense_values = [0] * 5

        for seq in self.board.iter_sequences(
            exclude_corner_extensions=True, includes_positions=(pos,)
        ):
            for team in self.board.teams:
                if team is self.player.team:
                    continue
                completion, one_eyeds_required = sequence_completion(
                    seq, self.board, team
                )

                if completion is None:
                    continue
                if one_eyeds_required >= 2:
                    continue

                dvalue = 0
                if move_type == MoveType.PLACE_CHIP:
                    # Placing a chip is essentially a full-blockage of
                    # a sequence.  Count it as a total defense point.
                    dvalue += 1
                else:
                    # Removing a chip only counts if we are removing
                    # this team's chip.
                    board_card, chip = self.board.getpos(pos)
                    if chip.team is not team:
                        continue
                    dvalue += 0.75
                if one_eyeds_required:
                    dvalue *= 0.25
                defense_values[completion] += dvalue

        if self.debug_moves:
            print("  DEFENSE={}".format(defense_values))

        return defense_values

    def _aligment_move_weights(self, move):
        card, move_type, pos = move
        alignment_values = [0] * 5

    def move_weight(self, move):
        card, move_type, pos = move

        weight = 0

        if self.debug_moves:
            print("Play {}:".format(move))
        offense_weights = self._offense_move_weights(move)
        for w, m in zip(offense_weights, self.offense_multipliers):
            weight += w * m

        for w, m in zip(self._defense_move_weights(move), self.defense_multipliers):
            weight += w * m

        # Discourage spending joker if possible.
        if card == "JJ":
            weight *= self.joker_multiplier

        # Discourage playing a two-eyed jack over a regular card.
        if card in two_eyeds:
            weight *= self.two_eyed_multiplier

        # Prefer two-eyeds only for completing sequences.
        if (card in two_eyeds or card == "JJ") and offense_weights[4] == 0:
            weight *= self.two_eyed_non_completion_multiplier

        # Always prefer winning.
        if (
            len(self.board.get_winning_sequences_for_team(self.player.team))
            + offense_weights[4]
            >= self.sequences_to_win
        ):
            weight *= 9999

        return weight


def play_game(teams, message=print):
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
    deck = list(all_cards)
    random.shuffle(deck)
    for player in players:
        for _ in range(cards_in_hand):
            player.hand.append(deck.pop())

    for player in itertools.cycle(players):
        message("{}'s turn".format(player))
        message("{}".format(board))

        # Evaluate any dead cards.
        for card in player.hand:
            if card in one_eyeds:
                continue
            it = board.iter_moves(card, player.team)
            try:
                next(it)
            except StopIteration:
                # Card is dead!
                if player.strategy.query_dead_card(card):
                    # They want it gone.
                    message("{} discarded a dead {}".format(player, card))
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
            message("{} played the {} at {}".format(player, card, pos))
        else:
            board_card, board_chip = board.getpos(pos)
            board.remove_chip(card, pos, player.team)
            message(
                "{} removed {}'s chip on the {} at {}".format(
                    player, board_chip.team, board_card, pos
                )
            )

        for notify_player in players:
            if notify_player is player:
                continue
            notify_player.strategy.notify_move(player, (card, action, pos))

        # See if their team has won.
        winning_sequences = board.get_winning_sequences_for_team(player.team)

        if len(winning_sequences) >= sequences_to_win:
            message("{}".format(board))
            message(
                "{} has won with {} sequences {!r}!".format(
                    player.team, len(winning_sequences), winning_sequences
                )
            )
            return player.team

        if deck:
            card = deck.pop()
            player.strategy.notify_pickup(card)
            player.hand.append(card)


def main():
    teams = {
        "blue": Team(TeamColor.BLUE),
        "green": Team(TeamColor.GREEN),
        "red": Team(TeamColor.RED),
    }

    stnums = {}

    parser = argparse.ArgumentParser()
    parser.add_argument("players", nargs="+")
    opts = parser.parse_args()

    for playerspec in opts.players:
        teamcolor, strategy_name_raw, *sargs_raw = playerspec.split(":")

        sargs = []
        skwargs = {}
        for arg in sargs_raw:
            m = re.fullmatch(r"\s*(\w+)\s*=(.*)", arg)
            if m:
                skwargs[m.group(1)] = ast.literal_eval(m.group(2))
            else:
                sargs.append(ast.literal_eval(arg))

        strategy_cls = (
            globals().get(strategy_name_raw)
            or globals()["{}Strategy".format(strategy_name_raw)]
        )
        strategy = strategy_cls(*sargs, **skwargs)
        stnum = stnums.get(strategy_cls, 0) + 1
        stnums[strategy_cls] = stnum
        team = teams[teamcolor.lower()]
        player = Player("{}{}".format(strategy_cls.__name__, stnum), team, strategy)

    play_game([team for team in teams.values() if team.players])


if __name__ == "__main__":
    main()
