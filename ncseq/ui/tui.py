import curses
import functools

from ncseq import game
from ncseq.ui import console


def manhattan_dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class TUI(console.ConsoleUI):
    def __init__(self):
        self.screen = curses.initscr()
        self.screen.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(False)
        curses.mousemask(curses.BUTTON1_CLICKED)

        self._loglines = []
        self._player = None
        self._board = None
        self._board_caption = ""
        self._board_clicked_pos = None
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
        self._mousemap = []

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
        if key == curses.KEY_MOUSE:
            try:
                _, x, y, _, state = curses.getmouse()
            except curses.error:
                pass
            else:
                for handler in self._mousemap:
                    rv = handler(y, x, state)
                    if rv:
                        return rv
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

    def _do_alert(self, message, buttons=("OK",)):
        self._alert = (message, buttons, 0)
        self._redraw()
        while self._alert:
            key = self._getch()
            message, buttons, i = self._alert
            if key == curses.KEY_ENTER:
                self._alert = None
                return buttons[i]
            if key == curses.KEY_LEFT:
                self._alert = (message, buttons, (i - 1) % len(buttons))
                self._redraw()
            elif key == curses.KEY_RIGHT:
                self._alert = (message, buttons, (i + 1) % len(buttons))
                self._redraw()

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
        self._log_message(f"{player} played the {game.pretty_card(card)} at {pos}")

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
            f"{player} used the {game.pretty_card(card)} to remove {team_text}'s "
            f"chip on the {game.pretty_card(board_card)} at {pos}",
            [button_text],
        )

    def game_over(self, winning_team, sequences, shut_out=False):
        msg = f"{winning_team} has won with {len(sequences)} sequences!"
        if shut_out:
            msg += "\n\nIt was a shut out."
        return self._do_alert(msg, ["Exit", "Keep Playing"])

    def player_has_empty_hand(self, player, sequences):
        scores = "\n".join(f"{k}: {len(v)}" for k, v in sequences.items())
        self._do_alert(
            f"{player} has an empty hand.  The final scores are:\n\n{scores}",
            ["Exit"],
        )

    def _hand_click_handler(self, y, x, state, x_start, card_space):
        if not (3 <= y <= 5):
            return
        x -= x_start
        if x < 0:
            return
        idx = x // card_space
        if idx >= len(self._hand):
            return
        self._hand_ptr = idx
        return curses.KEY_ENTER

    def _choose_card(self, player):
        if self._hand_ptr >= 0:
            # Mouse event selected a new card already.
            selected_card = self._hand[self._hand_ptr]
            self._hand_ptr = -1
            self._hinted_positions = []
            return selected_card

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

        if key == ord(" "):
            idx = self._movelist.index(self._move)
            if self._invert_board:
                idx -= 1
            else:
                idx += 1
            idx %= len(self._movelist)
            return self._movelist[idx]

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

    def _board_click_handler(self, y, x, state, card_space):
        row = y // card_space
        column = x // card_space
        if self._invert_board:
            row = 9 - row
            column = 9 - column
        pos = (row, column)
        if pos not in self._hinted_positions:
            return
        self._board_clicked_pos = pos
        return curses.KEY_ENTER

    def query_move(self, player, board):
        self._player = player
        self._board = board
        self._hand = game.sort_hand(player.hand)
        self._board_clicked_pos = None

        while True:
            chosen_card = self._choose_card(player)

            self._movelist = list(self._board.iter_moves(chosen_card, player.team))
            if len(self._movelist) == 1:
                _, action, _ = self._movelist[0]
                if action == game.MoveType.DISCARD_DEAD_CARD:
                    if self._query_dead_card(chosen_card):
                        return self._movelist[0]
                    else:
                        continue

            self._hand_line = "Your Hand:  (Press Esc to choose another card)"
            self._hinted_positions = [pos for _, _, pos in self._movelist]
            self._move = max(self._movelist, key=game.move_weight_centermost)

            while True:
                if self._board_clicked_pos:
                    self._move = None
                    moves = [
                        move
                        for move in self._movelist
                        if move[2] == self._board_clicked_pos
                    ]
                    self._board_clicked_pos = None
                    assert len(moves) == 1
                    self._movelist = []
                    self._hinted_positions = []
                    self._board_caption = ""
                    return moves[0]
                move_desc = game.describe_move(self._move, self._board)
                self._board_caption = (
                    f"Press Enter to {move_desc[0].lower()}{move_desc[1:]}"
                )
                self._redraw()
                key = self._getch()
                if self._board_clicked_pos:
                    continue
                if key == 27:
                    self._move = None
                    break
                if self._hand_ptr >= 0 and key == curses.KEY_ENTER:
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

    def _query_dead_card(self, card):
        self._dead_card = card

        while self._dead_card:
            self._redraw()
            key = self._getch()
            if key == curses.KEY_ENTER:
                self._dead_card = None
                if self._dead_card_discard:
                    self._discard = card
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                self._dead_card_discard = not self._dead_card_discard
        return self._dead_card_discard

    def _draw_card(
        self,
        y,
        x,
        card,
        chip=None,
        selected=False,
        hinted=False,
        new=False,
        dead=False,
    ):
        bg_color = curses.COLOR_WHITE
        if hinted:
            bg_color = curses.COLOR_YELLOW
        if selected:
            bg_color = curses.COLOR_CYAN

        fg_color = (
            curses.COLOR_RED
            if card is not game.CORN and card[-1] in ("H", "D")
            else curses.COLOR_BLACK
        )
        chip_fg_color = curses.COLOR_WHITE

        if chip:
            chip_color = {
                game.TeamColor.BLUE: curses.COLOR_BLUE,
                game.TeamColor.GREEN: curses.COLOR_GREEN,
                game.TeamColor.RED: curses.COLOR_RED,
            }[chip.team.color]
        else:
            chip_color = bg_color

        if card is game.CORN:
            chip_color = curses.COLOR_BLACK
            card_label = "   "
        else:
            card_label = f"{game.pretty_card(card):>3}"[:3].upper()

        if card in game.TWO_EYEDS:
            chip_chr = "‥"
            chip_color = bg_color
            chip_fg_color = curses.COLOR_BLACK
        elif card in game.ONE_EYEDS:
            chip_chr = "."
            chip_color = bg_color
            chip_fg_color = curses.COLOR_BLACK
        elif chip and chip.is_flipped():
            chip_chr = "@"
        elif chip or card is game.CORN:
            chip_chr = " "
        else:
            chip_chr = ""

        base_attr = 0
        if new or dead:
            base_attr |= curses.A_BOLD

        bottom_line = "   "
        if new:
            bottom_line = "NEW"
        if dead:
            bottom_line = " ☠ "

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
            bottom_line,
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
        self,
        y,
        x,
        text,
        fg_color=curses.COLOR_BLACK,
        bg_color=curses.COLOR_WHITE,
        on_click=None,
    ):
        self._fill(y, x, 3, len(text) + 2, bg_color=bg_color)
        self.screen.addstr(y + 1, x + 1, text, self._color_pair(fg_color, bg_color))
        if on_click:

            def mouse_handler(mouse_y, mouse_x, state):
                if (
                    y <= mouse_y < y + 3
                    and x <= mouse_x < x + len(text) + 2
                    and state & curses.BUTTON1_CLICKED
                ):
                    return on_click()

            self._mousemap.append(mouse_handler)

    def _redraw(self):
        self._mousemap = []
        screen_lines, screen_columns = self.screen.getmaxyx()
        self._fill(0, 0, screen_lines - 1, screen_columns, curses.COLOR_GREEN)
        if screen_lines > 50 and screen_columns > 100:
            card_space = 4
        else:
            card_space = 3
        board_space = (card_space * 10) + 1

        if self._board:
            selected_pos = self._move[2] if self._move else None
            for pos in game.iter_pos():
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

        if self._hinted_positions:
            self._mousemap.append(
                functools.partial(
                    self._board_click_handler,
                    card_space=card_space,
                ),
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
                    dead=self._board.card_is_dead(card, self._player.team),
                )
                self._mousemap.append(
                    functools.partial(
                        self._hand_click_handler,
                        x_start=board_space + 1,
                        card_space=card_space,
                    ),
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
            self._mousemap = []
            dialog_y = (screen_lines // 2) - 6
            dialog_x = (screen_columns // 2) - 26
            self._fill(dialog_y, dialog_x, 12, 52, curses.COLOR_BLUE, shadow=True)
            self.screen.addstr(
                dialog_y + 1,
                dialog_x + 1,
                "This card is dead and cannot be played right now.",
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

            def on_click_yes():
                self._dead_card_discard = True
                self._dead_card = None

            def on_click_no():
                self._dead_card_discard = False
                self._dead_card = None

            self._button(
                dialog_y + 8,
                dialog_x + 41,
                "YES",
                bg_color=curses.COLOR_CYAN
                if self._dead_card_discard
                else curses.COLOR_WHITE,
                on_click=on_click_yes,
            )
            self._button(
                dialog_y + 8,
                dialog_x + 47,
                "NO",
                bg_color=curses.COLOR_WHITE
                if self._dead_card_discard
                else curses.COLOR_CYAN,
                on_click=on_click_no,
            )

        if self._alert:
            self._mousemap = []
            alert_text, buttons, ptr = self._alert
            alert_lines = alert_text.splitlines()
            width = max(
                max(len(x) for x in alert_lines) + 2,
                sum(len(x) + 3 for x in buttons) + 2,
            )
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

            def on_click_alert_button(i):
                self._alert = (alert_text, buttons, i)
                return curses.KEY_ENTER

            x_pos = dialog_x + width
            for i, btn in reversed(list(enumerate(buttons))):
                x_pos -= len(btn) + 3
                self._button(
                    dialog_y + height - 4,
                    x_pos,
                    btn,
                    bg_color=curses.COLOR_CYAN if i == ptr else curses.COLOR_WHITE,
                    on_click=functools.partial(on_click_alert_button, i),
                )

        self.screen.refresh()
