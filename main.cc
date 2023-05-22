#include <absl/container/flat_hash_map.h>
#include <absl/random/bit_gen_ref.h>
#include <absl/random/random.h>
#include <absl/strings/str_format.h>
#include <grpc/grpc.h>
#include <grpcpp/security/server_credentials.h>
#include <grpcpp/server.h>
#include <grpcpp/server_builder.h>
#include <grpcpp/server_context.h>

#include <cstdint>
#include <string>

#include "generated/sequence.grpc.pb.h"
#include "generated/sequence.pb.h"

using grpc::Server;
using grpc::ServerBuilder;
using grpc::ServerContext;
using grpc::Status;

std::string GenerateGameCode(absl::BitGenRef gen) {
  std::string result = "";

  for (int i = 0; i < 6; i++) {
    result += absl::StrFormat("%d", absl::Uniform<int>(gen, 0, 10));
  }
  return result;
}

uint32_t GenerateToken(absl::BitGenRef gen) {
  return absl::Uniform<uint32_t>(gen);
}

class Game {
 public:
  std::optional<Player *> GetPlayerById(uint32_t id) {
    for (int i = 0; i < state.players_size(); i++) {
      auto player = state.mutable_players(i);
      if (player->id() == id) {
        return player;
      }
    }

    return std::nullopt;
  }

  std::optional<Player *> GetPlayerByToken(uint32_t token) {
    auto search = token_to_id.find(token);
    if (search == token_to_id.end()) {
      return std::nullopt;
    }

    return GetPlayerById(search->second);
  }

  uint32_t admin_token;
  GameState state;
  absl::flat_hash_map<uint32_t, uint32_t> token_to_id;
};

class GameServerImpl final : public GameServer::Service {
 public:
  Status NewGame(ServerContext *context, const NewGameRequest *request,
                 NewGameResponse *response) override {
    std::string game_code;

    do {
      game_code = GenerateGameCode(rng);
    } while (games_by_code.contains(game_code));

    auto game = std::make_unique<Game>();
    game->admin_token = GenerateToken(rng);

    response->set_game_code(game_code);
    response->set_admin_token(game->admin_token);

    games_by_code.try_emplace(game_code, std::move(game));
    return Status::OK;
  }

  Status JoinGame(ServerContext *context, const JoinGameRequest *request,
                  JoinGameResponse *response) override {
    auto search = games_by_code.find(request->game_code());
    if (search == games_by_code.end()) {
      return Status(grpc::NOT_FOUND,
                    absl::StrFormat("No game with code \"%s\" exists!",
                                    request->game_code()));
    }

    auto game = search->second.get();
    auto player = game->state.add_players();
    auto token = GenerateToken(rng);
    auto id = GenerateToken(rng);

    player->set_id(id);
    response->set_player_token(token);
    game->token_to_id.try_emplace(token, id);
    return Status::OK;
  }

 private:
  absl::BitGen rng;
  absl::flat_hash_map<std::string, std::unique_ptr<Game>> games_by_code;
};

int main(int argc, char *argv[]) {
  GameServerImpl service;
  ServerBuilder builder;
  builder.AddListeningPort("0.0.0.0:7378", grpc::InsecureServerCredentials());
  builder.RegisterService(&service);
  std::unique_ptr<Server> server(builder.BuildAndStart());
  server->Wait();
  return 0;
}
