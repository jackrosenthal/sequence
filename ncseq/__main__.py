#!/usr/bin/env python3

import argparse
import ast
import random
import re

from ncseq import game
from ncseq.ui import console, tui


def sequence_completion(seq, board, team):
    completion = 0
    one_eyeds_required = 0
    shared_chip_encountered = False
    for pos in seq:
        card, chip = board.getpos(pos)
        if card is game.CORN:
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


class BaseStrategy:
    def set_game_parameters(self, player, board, sequences_to_win, cards_per_player):
        self.player = player
        self.board = board
        self.sequences_to_win = sequences_to_win
        self.cards_per_player = cards_per_player

    def notify_move(self, player, move):
        pass

    def notify_pickup(self, card):
        pass

    def query_move(self):
        raise NotImplementedError


class RandomStrategy(BaseStrategy):
    def query_move(self):
        moves = [
            move
            for card in self.player.hand
            for move in self.board.iter_moves(card, self.player.team)
        ]
        return random.choice(moves)


class HumanStrategy(BaseStrategy):
    def notify_pickup(self, card):
        self.player.ui.notify_pickup(self.player, card)

    def query_move(self):
        return self.player.ui.query_move(self.player, self.board)


class WeightedBaseStrategy(BaseStrategy):
    def move_weight(self, move):
        raise NotImplementedError

    def query_move(self):
        return max(
            (
                move
                for card in game.unique_cards_by_action(self.player.hand)
                for move in self.board.iter_moves(card, self.player.team)
            ),
            key=lambda move: self.move_weight(move),
        )


class CentermostStrategy(WeightedBaseStrategy):
    def move_weight(self, move):
        return game.move_weight_centermost(move)


class SimpleWeightingStrategy(WeightedBaseStrategy):
    DEFAULT_OFFENSE_MULTIPLIERS = (1, 1.1, 2, 4, 10)
    DEFAULT_DEFENSE_MULTIPLIERS = (0.1, 0.15, 0.5, 1.5, 5)

    def __init__(
        self,
        offense_multipliers=None,
        defense_multipliers=None,
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
        self.debug_moves = debug_moves
        self.two_eyed_non_completion_multiplier = two_eyed_non_completion_multiplier
        self.two_eyed_multiplier = two_eyed_multiplier
        self.joker_multiplier = joker_multiplier
        self.cards_played = []

    def _offense_move_weights(self, move):
        num_one_eyeds = sum(
            1 for card in self.player.hand if card in game.ONE_EYEDS or card == "JJ"
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
            if move_type == game.MoveType.REMOVE_CHIP:
                if one_eyeds_required <= completion:
                    completion -= one_eyeds_required
                else:
                    continue

            offense_values[completion] += 1

        if self.debug_moves:
            print(f"  OFFENSE={offense_values}")
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
                if move_type == game.MoveType.PLACE_CHIP:
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
            print(f"  DEFENSE={defense_values}")

        return defense_values

    def move_weight(self, move):
        card, move_type, pos = move

        # Always discard dead cards.
        if move_type == game.MoveType.DISCARD_DEAD_CARD:
            if card in game.ONE_EYEDS:
                return 0
            return 9999 * 9999

        weight = 0

        if self.debug_moves:
            print(f"Play {move}:")
        offense_weights = self._offense_move_weights(move)
        for w, m in zip(offense_weights, self.offense_multipliers):
            weight += w * m

        for w, m in zip(self._defense_move_weights(move), self.defense_multipliers):
            weight += w * m

        # Discourage spending joker if possible.
        if card == "JJ":
            weight *= self.joker_multiplier

        # Discourage playing a two-eyed jack over a regular card.
        if card in game.TWO_EYEDS:
            weight *= self.two_eyed_multiplier

        # Prefer two-eyeds only for completing sequences.
        if (card in game.TWO_EYEDS or card == "JJ") and offense_weights[4] == 0:
            weight *= self.two_eyed_non_completion_multiplier

        # Always prefer winning.
        if (
            len(self.board.get_winning_sequences_for_team(self.player.team))
            + offense_weights[4]
            >= self.sequences_to_win
        ):
            weight *= 9999

        return weight


def main():
    teams = {
        "blue": game.Team(game.TeamColor.BLUE),
        "green": game.Team(game.TeamColor.GREEN),
        "red": game.Team(game.TeamColor.RED),
    }

    stnums = {}

    parser = argparse.ArgumentParser()
    parser.add_argument("--tui", action="store_true")
    parser.add_argument("players", nargs="+")
    opts = parser.parse_args()

    if opts.tui:
        ui = tui.TUI()
    else:
        ui = console.ConsoleUI()

    try:
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
                or globals()[f"{strategy_name_raw}Strategy"]
            )
            strategy = strategy_cls(*sargs, **skwargs)
            stnum = stnums.get(strategy_cls, 0) + 1
            stnums[strategy_cls] = stnum
            team = teams[teamcolor.lower()]
            team.add_player(
                name=f"{strategy_cls.__name__}{stnum}",
                strategy=strategy,
                ui=ui,
            )

        game.play_game([team for team in teams.values() if team.players], ui)
    finally:
        ui.exit()


if __name__ == "__main__":
    main()
