from ncseq import game


class ConsoleUI:
    def _log_message(self, message):
        print(message)

    def notify_turn(self, player):
        self._log_message(f"{player}'s turn")

    def update_board(self, board):
        self._log_message(str(board))

    def notify_dead_card_discard(self, player, card):
        self._log_message(f"{player} discarded a dead {game.pretty_card(card)}")

    def play_chip(self, player, card, pos):
        self._log_message(f"{player} played the {game.pretty_card(card)} at {pos}")

    def remove_chip(self, player, card, team, board_card, pos):
        self._log_message(
            f"{player} used a {game.pretty_card(card)} to remove {team}'s chip on "
            f"the {game.pretty_card(board_card)} at {pos}"
        )

    def game_over(self, winning_team, winning_sequences, shut_out=False):
        self._log_message(
            f"{winning_team} has won with {len(winning_sequences)} sequences!"
        )
        return "Exit"

    def player_has_empty_hand(self, player, sequences):
        scores = ", ".join(f"{k}: {len(v)}" for k, v in sequences.items())
        self._log_message(
            f"{player} has an empty hand.  The final scores are: {scores}"
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
        hand = game.sort_hand(player.hand)
        while True:
            card = input(f"[{player}] Which card to play ({', '.join(hand)})? ")
            card = card.upper().strip()
            if card not in player.hand:
                self._log_message("That card is not in your hand!")
                continue
            moves = list(board.iter_moves(card, player.team))

            prompt = "How do you want to play it?\n\n"
            for i, move in enumerate(moves):
                prompt += f"{i + 1:>3}. {game.describe_move(move, board)}\n"
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
