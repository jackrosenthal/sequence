#!/usr/bin/env python3

import argparse
import ast
import curses
import enum
import functools
import io
import itertools
import random
import re

ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "X", "J", "Q", "K", "A"]
suits = ["H", "C", "D", "S"]
all_cards = ["{}{}".format(rank, suit) for rank in ranks for suit in suits] * 2 + ["JJ"]
one_eyeds = ["JS", "JH"]
two_eyeds = ["JC", "JD"]


CORN = object()


def manhattan_dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


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
        return "{} ({})".format(self.name, self.team)


def sort_hand(hand):
    return sorted(
        hand,
        key=lambda card: (
            card == "JJ",
            card in two_eyeds,
            card in one_eyeds,
            "HCDS".find(card[1]),
            "23456789XQKA".find(card[0]),
        ),
    )


def describe_move(move, board):
    card, action, pos = move
    board_card, board_chip = board.getpos(pos)
    if action == MoveType.PLACE_CHIP:
        return f"Play on the {board_card} at {pos}."
    else:  # action == MoveType.REMOVE_CHIP
        return f"Remove the {board_chip.team}'s chip on the {board_card} at {pos}."


class ConsoleUI:
    def _log_message(self, message):
        print(message)

    def notify_turn(self, player):
        self._log_message(f"{player}'s turn")

    def update_board(self, board):
        self._log_message(str(board))

    def notify_dead_card_discard(self, player, card):
        self._log_message(f"{player} discarded a dead {card}")

    def play_chip(self, player, card, pos):
        self._log_message(f"{player} played the {card} at {pos}")

    def remove_chip(self, player, card, team, board_card, pos):
        self._log_message(
            f"{player} used a {card} to remove {team}'s chip on the "
            f"{board_card} at {pos}"
        )

    def game_over(self, winning_team, winning_sequences, shut_out=False):
        self._log_message(
            f"{winning_team} has won with {len(winning_sequences)} sequences!"
        )

    def notify_pickup(self, player, card):
        self._log_message(f"[{player}] You picked up the {card}.")

    def query_dead_card(self, player, card):
        while True:
            answer = input(
                f"[{player}] You have a dead card ({card}) in your hand. "
                "Want to discard it (Y/n)? "
            )
            answer = answer.lower().strip()
            if not answer or answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

    def query_move(self, player, board):
        hand = sort_hand(player.hand)
        while True:
            card = input(f"[{player}] Which card to play ({', '.join(hand)})? ")
            card = card.upper().strip()
            if card not in player.hand:
                self._log_message("That card is not in your hand!")
                continue
            moves = list(board.iter_moves(card, player.team))

            prompt = "How do you want to play it?\n\n"
            for i, move in enumerate(moves):
                prompt += f"{i + 1:>3}. {describe_move(move, board)}\n"
            prompt += (
                f"{len(moves) + 1:>3}. Choose a different card to play from your "
                "hand.\n\nYour choice? "
            )
            move_choice = input(prompt)
            try:
                move_idx = int(move_choice)
            except ValueError:
                self._log_message("Input not valid, expected an integer.")
                continue
            if move_idx == len(moves) + 1:
                continue
            if not (1 <= move_idx <= len(moves)):
                self._log_message("Input not valid.")
                continue
            return moves[move_idx - 1]

    def exit(self):
        return


class TUI(ConsoleUI):
    def __init__(self):
        self.screen = curses.initscr()
        self.screen.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(False)

        self._loglines = []
        self._player = None
        self._board = None
        self._board_caption = ""
        self._invert_board = False
        self._hand = None
        self._hand_line = "Your Hand:"
        self._hand_ptr = -1
        self._new_card = None
        self._discard = None
        self._movelist = []
        self._hinted_positions = []
        self._move = None
        self._turn_display = ""
        self._color_pairs = {}
        self._dead_card = None
        self._dead_card_discard = True
        self._alert = None

        # Default background/foreground
        self._background = self._color_pair(curses.COLOR_WHITE, curses.COLOR_GREEN)
        self.screen.attron(self._background)

    def exit(self):
        self.screen.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        curses.curs_set(True)

    def _getch(self):
        key = self.screen.getch()
        if key in (10, 13):
            key = curses.KEY_ENTER
        if key == ord("i") or key == ord("I"):
            self._invert_board = not self._invert_board
            self._redraw()
        return key

    def _color_pair(self, fg, bg):
        if (fg, bg) not in self._color_pairs:
            pair_idx = len(self._color_pairs) + 16
            curses.init_pair(pair_idx, fg, bg)
            self._color_pairs[(fg, bg)] = pair_idx
        return curses.color_pair(self._color_pairs[(fg, bg)])

    def _log_message(self, message):
        self._loglines.append(message)
        self._redraw()

    def _do_alert(self, message, button="OK"):
        self._alert = (message, button)
        self._redraw()
        while True:
            key = self._getch()
            if key == curses.KEY_ENTER:
                self._alert = None
                return

    def update_board(self, board):
        self._board = board
        self._redraw()

    def notify_turn(self, player):
        self._turn_display = f"{player}'s turn"
        self._redraw()

    def notify_pickup(self, player, card):
        self._new_card = card

    def play_chip(self, player, card, pos):
        self._discard = card
        self._log_message(f"{player} played the {card} at {pos}")

    def remove_chip(self, player, card, team, board_card, pos):
        self._discard = card
        if player is self._player:
            return
        if self._player and team is self._player.team:
            team_text = "your team"
            button_text = "Bummer"
        else:
            team_text = str(team)
            button_text = "OK"
        self._do_alert(
            f"{player} used the {card} to remove {team_text}'s chip on the "
            f"{board_card} at {pos}",
            button_text,
        )

    def game_over(self, winning_team, sequences, shut_out=False):
        msg = f"{winning_team} has won with {len(sequences)} sequences!"
        if shut_out:
            msg += "\n\nIt was a shut out."
        self._do_alert(msg, "Exit")

    def _choose_card(self, player):
        self._hand_line = "Choose a card from your hand to play:"
        self._hand_ptr = 0
        self._movelist = []

        while True:
            self._hinted_positions = [
                pos
                for _, _, pos in self._board.iter_moves(
                    self._hand[self._hand_ptr], player.team
                )
            ]
            self._redraw()
            key = self._getch()
            if key == curses.KEY_LEFT:
                self._hand_ptr = (self._hand_ptr - 1) % len(self._hand)
            elif key == curses.KEY_RIGHT:
                self._hand_ptr = (self._hand_ptr + 1) % len(self._hand)
            elif key == curses.KEY_ENTER:
                selected_card = self._hand[self._hand_ptr]
                self._hand_ptr = -1
                self._hinted_positions = []
                return selected_card

    def _next_move_from_keypress(self, key):
        _, _, cur_pos = self._move
        cur_row, cur_col = cur_pos

        if self._invert_board:
            key = {
                curses.KEY_UP: curses.KEY_DOWN,
                curses.KEY_DOWN: curses.KEY_UP,
                curses.KEY_LEFT: curses.KEY_RIGHT,
                curses.KEY_RIGHT: curses.KEY_LEFT,
            }.get(key, key)

        qualfunc = {
            curses.KEY_UP: lambda r, c: r < cur_row,
            curses.KEY_DOWN: lambda r, c: r > cur_row,
            curses.KEY_LEFT: lambda r, c: c < cur_col,
            curses.KEY_RIGHT: lambda r, c: c > cur_col,
        }.get(key, lambda r, c: False)

        qual_moves = [m for m in self._movelist if qualfunc(m[2][0], m[2][1])]
        if not qual_moves:
            return self._move

        # Prefer moves which are in the same row or column.
        qual_moves_sharing_dimen = [
            m for m in qual_moves if m[2][0] == cur_row or m[2][1] == cur_col
        ]
        if qual_moves_sharing_dimen:
            qual_moves = qual_moves_sharing_dimen

        return min(qual_moves, key=lambda move: manhattan_dist(move[2], cur_pos))

    def query_move(self, player, board):
        self._player = player
        self._board = board
        self._hand = sort_hand(player.hand)

        while True:
            chosen_card = self._choose_card(player)

            self._movelist = list(self._board.iter_moves(chosen_card, player.team))
            if not self._movelist:
                self._do_alert("The card is dead. It cannot be played right now.")
                continue

            self._hand_line = "Your Hand:  (Press Esc to choose another card)"
            self._hinted_positions = [pos for _, _, pos in self._movelist]
            self._move = self._movelist[0]

            while True:
                self._board_caption = (
                    f"Press Enter to {describe_move(self._move, self._board).lower()}"
                )
                self._redraw()
                key = self._getch()
                if key == 27:
                    self._move = None
                    break
                if key == curses.KEY_ENTER:
                    move = self._move
                    self._movelist = []
                    self._hinted_positions = []
                    self._board_caption = ""
                    self._hand_line = "Your Hand:"
                    self._move = None
                    return move
                self._move = self._next_move_from_keypress(key)

    def query_dead_card(self, player, card):
        self._dead_card = card

        while True:
            self._redraw()
            key = self._getch()
            if key == curses.KEY_ENTER:
                self._dead_card = None
                if self._dead_card_discard:
                    self._discard = card
                return self._dead_card_discard
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                self._dead_card_discard = not self._dead_card_discard

    def _draw_card(
        self, y, x, card, chip=None, selected=False, hinted=False, new=False
    ):
        bg_color = curses.COLOR_WHITE
        if hinted:
            bg_color = curses.COLOR_YELLOW
        if selected:
            bg_color = curses.COLOR_CYAN

        fg_color = (
            curses.COLOR_RED
            if card is not CORN and card[-1] in ("H", "D")
            else curses.COLOR_BLACK
        )
        chip_fg_color = curses.COLOR_WHITE

        if chip:
            chip_color = {
                TeamColor.BLUE: curses.COLOR_BLUE,
                TeamColor.GREEN: curses.COLOR_GREEN,
                TeamColor.RED: curses.COLOR_RED,
            }[chip.team.color]
        else:
            chip_color = bg_color

        if card is CORN:
            chip_color = curses.COLOR_BLACK
            card_label = "   "
        elif card == "JJ":
            card_label = "JOK"
        else:
            card_suit = {
                "H": "♥",
                "C": "♣",
                "D": "♦",
                "S": "♠",
            }[card[-1]]
            card_rank = "10" if card[0] == "X" else card[0]
            card_label = f"{card_rank + card_suit:>3}"

        if card in two_eyeds:
            chip_chr = "‥"
            chip_color = bg_color
            chip_fg_color = curses.COLOR_BLACK
        elif card in one_eyeds:
            chip_chr = "."
            chip_color = bg_color
            chip_fg_color = curses.COLOR_BLACK
        elif chip and chip.is_flipped():
            chip_chr = "@"
        elif chip or card is CORN:
            chip_chr = " "
        else:
            chip_chr = ""

        base_attr = 0
        if new:
            base_attr |= curses.A_BOLD

        self.screen.addstr(
            y, x, card_label, base_attr | self._color_pair(fg_color, bg_color)
        )
        self.screen.addstr(
            y + 1, x, "   ", base_attr | self._color_pair(fg_color, bg_color)
        )
        if chip_chr:
            self.screen.addstr(
                y + 1,
                x + 1,
                chip_chr,
                base_attr | self._color_pair(chip_fg_color, chip_color),
            )
        self.screen.addstr(
            y + 2,
            x,
            "NEW" if new else "   ",
            base_attr | self._color_pair(fg_color, bg_color),
        )

    def _fill(self, y, x, height, width, bg_color, shadow=False):
        if shadow:
            self._fill(y + 1, x + 1, height, width, curses.COLOR_BLACK)
        for i in range(height):
            self.screen.addstr(
                y + i, x, " " * width, self._color_pair(bg_color, bg_color)
            )

    def _button(
        self, y, x, text, fg_color=curses.COLOR_BLACK, bg_color=curses.COLOR_WHITE
    ):
        self._fill(y, x, 3, len(text) + 2, bg_color=bg_color)
        self.screen.addstr(y + 1, x + 1, text, self._color_pair(fg_color, bg_color))

    def _redraw(self):
        screen_lines, screen_columns = self.screen.getmaxyx()
        self._fill(0, 0, screen_lines - 1, screen_columns, curses.COLOR_GREEN)
        if screen_lines > 50 and screen_columns > 100:
            card_space = 4
        else:
            card_space = 3
        board_space = (card_space * 10) + 1

        if self._board:
            selected_pos = self._move[2] if self._move else None
            for pos in iter_pos():
                card, chip = self._board.getpos(pos)
                row, col = pos
                if self._invert_board:
                    row = 9 - row
                    col = 9 - col
                self._draw_card(
                    row * card_space,
                    col * card_space,
                    card,
                    chip=chip,
                    selected=pos == selected_pos,
                    hinted=pos in self._hinted_positions,
                )
            self.screen.addstr(
                board_space - 1,
                0,
                self._board_caption.ljust(screen_columns),
                curses.A_BOLD | self._color_pair(curses.COLOR_WHITE, curses.COLOR_RED),
            )

        if self._hand:
            self.screen.addstr(2, board_space + 1, self._hand_line)
            seen_new_card = False
            for i, card in enumerate(self._hand):
                if not seen_new_card and self._new_card == card:
                    new = True
                    seen_new_card = True
                else:
                    new = False
                self._draw_card(
                    3,
                    board_space + 1 + (i * card_space),
                    card,
                    selected=i == self._hand_ptr,
                    new=new,
                )

        if self._discard:
            self.screen.addstr(7, board_space + 1, "Discard")
            self._draw_card(8, board_space + 1, self._discard)

        self.screen.addstr(
            0, board_space + 1, self._turn_display, curses.A_BOLD | self._background
        )

        disp_log = self._loglines[-(screen_lines - board_space - 1) :]
        while len(disp_log) < (screen_lines - board_space - 1):
            disp_log.append("")

        for i, line in enumerate(disp_log):
            self.screen.addstr(
                board_space + i,
                0,
                line.ljust(screen_columns),
                self._color_pair(curses.COLOR_BLACK, curses.COLOR_WHITE),
            )

        if self._dead_card:
            dialog_y = (screen_lines // 2) - 6
            dialog_x = (screen_columns // 2) - 20
            self._fill(dialog_y, dialog_x, 12, 40, curses.COLOR_BLUE, shadow=True)
            self.screen.addstr(
                dialog_y + 1,
                dialog_x + 1,
                "You have a dead card:",
                self._color_pair(curses.COLOR_WHITE, curses.COLOR_BLUE),
            )
            self._draw_card(
                dialog_y + 3,
                dialog_x + 5,
                self._dead_card,
            )
            self.screen.addstr(
                dialog_y + 7,
                dialog_x + 1,
                "Want to discard it?",
                self._color_pair(curses.COLOR_WHITE, curses.COLOR_BLUE),
            )
            self._button(
                dialog_y + 8,
                dialog_x + 29,
                "YES",
                bg_color=curses.COLOR_CYAN
                if self._dead_card_discard
                else curses.COLOR_WHITE,
            )
            self._button(
                dialog_y + 8,
                dialog_x + 35,
                "NO",
                bg_color=curses.COLOR_WHITE
                if self._dead_card_discard
                else curses.COLOR_CYAN,
            )

        if self._alert:
            alert_text, button_text = self._alert
            alert_lines = alert_text.splitlines()
            width = max(len(alert_text) + 2, len(button_text) + 4)
            height = 7 + len(alert_lines)
            dialog_y = (screen_lines // 2) - (height // 2)
            dialog_x = (screen_columns // 2) - (width // 2)
            self._fill(
                dialog_y, dialog_x, height, width, curses.COLOR_BLUE, shadow=True
            )
            for i, line in enumerate(alert_lines):
                self.screen.addstr(
                    dialog_y + 1 + i,
                    dialog_x + 1,
                    line,
                    self._color_pair(curses.COLOR_WHITE, curses.COLOR_BLUE),
                )
            self._button(
                dialog_y + height - 4,
                dialog_x + width - len(button_text) - 3,
                button_text,
                bg_color=curses.COLOR_CYAN,
            )

        self.screen.refresh()


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
            for move in self.board.iter_moves(card, self.player.team)
        ]
        return random.choice(moves)


class HumanStrategy(BaseStrategy):
    def notify_pickup(self, card):
        self.player.ui.notify_pickup(self.player, card)

    def query_dead_card(self, card):
        return self.player.ui.query_dead_card(self.player, card)

    def query_move(self):
        return self.player.ui.query_move(self.player, self.board)


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


class CentermostStrategy(WeightedBaseStrategy):
    def _coord_weight(self, val):
        if val in (4, 5):
            return 10000
        if val in (3, 6):
            return 1000
        if val in (2, 7):
            return 100
        if val in (1, 8):
            return 10
        return 1

    def move_weight(self, move):
        card, move_type, pos = move
        pos_x, pos_y = pos
        return self._coord_weight(pos_x) + self._coord_weight(pos_y)


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


def play_game(teams, ui):
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
        ui.notify_turn(player)
        ui.update_board(board)

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

        if len(winning_sequences) >= sequences_to_win:
            shut_out = True
            for team, seqs in sequences.items():
                if seqs and team is not player.team:
                    shut_out = False
            ui.update_board(board)
            ui.game_over(player.team, winning_sequences, shut_out=shut_out)
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
    parser.add_argument("--tui", action="store_true")
    parser.add_argument("players", nargs="+")
    opts = parser.parse_args()

    if opts.tui:
        ui = TUI()
    else:
        ui = ConsoleUI()

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
                or globals()["{}Strategy".format(strategy_name_raw)]
            )
            strategy = strategy_cls(*sargs, **skwargs)
            stnum = stnums.get(strategy_cls, 0) + 1
            stnums[strategy_cls] = stnum
            team = teams[teamcolor.lower()]
            team.add_player(
                name="{}{}".format(strategy_cls.__name__, stnum),
                strategy=strategy,
                ui=ui,
            )

        play_game([team for team in teams.values() if team.players], ui)
    finally:
        ui.exit()


if __name__ == "__main__":
    main()
