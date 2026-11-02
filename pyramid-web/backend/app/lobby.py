"""Lobby system for pyramid-web: rooms, players, WebSocket protocol.

Step 2 scope:
  - rooms identified by 4-letter codes (A-Z)
  - create (first player = host) / join (capped at 2 players)
  - player-list broadcasts on every membership change
  - host-only start_game -> game_started broadcast

Step 5 scope:
  - start_game deals a fresh random rack and broadcasts it in game_started
  - the room carries the current on-table ball state; ``shot`` runs the
    pooltool simulation in a worker thread and broadcasts shot_result with
    trajectory keyframes (event-based trajectory sampled on a 40 ms grid +
    event times)

Step 6 scope:
  - game modes: host picks one of free/combined/dynamic/classic via
    ``set_mode`` (lobby state only); ``start_game`` instantiates the vendored
    ruleset (see ``app/rules.py``) and the mode + full game snapshot ride
    every broadcast
  - turn enforcement: only the ruleset's active player may shoot or place
    the cue ball; a Classic call (ball + pocket) is required on called
    strokes and validated against the live balls / pocket ids
  - ``shot`` now drives ``Ruleset.process_and_advance`` inside the worker
    thread; ``shot_result`` carries the verdict (legal/reason), score,
    respotted/removed balls, and the next-stroke game state
  - ``place_cue`` implements ball-in-hand («с руки из дома» / «с руки»)
    with server-side validation
  - game over -> host rematch via ``start_game``

Step 8 scope:
  - every game snapshot is stamped with ``turn_started_ms`` (epoch ms when
    the current stroke's thinking time began) and ``now_ms`` (server epoch
    at build time, so clients can correct for clock skew). The turn clock
    is INFORMATIONAL: the vendored rulesets contain no shot-clock rule and
    lobby-level timeout enforcement would re-implement a rule, which the
    frozen-rules decisions forbid (see PROGRESS.md, Step 8).

Step 11 scope (architecture change — client-side JS physics):
  - the client simulates the stroke in its own browser (frontend/physics.js,
    vendored cannon-es) and sends ONE ``shot`` message when the balls stop:
    final resting positions + pocketed/cushion/first-contact events (see
    ``app/bridge.py``). The server runs NO pooltool physics for gameplay —
    it validates the report, reconstructs the synthetic ruleset input and
    calls ``process_and_advance`` synchronously (microseconds), then
    broadcasts ``shot_result`` WITHOUT keyframes: every client applies the
    authoritative post-rules state (the shooter's local view is corrected
    for respots / penalty removals, the opponent's board snaps to the final
    state). "Simulating shot…" cannot exist anymore; the only wait left is
    a microseconds-fast rules round-trip.

Design decisions (logged in pyramid-web/PROGRESS.md):
  - In-memory state, single process. Rooms are deleted when empty.
  - MAX_PLAYERS = 2 (Russian Pyramid is a two-player game; spectators are a
    possible Step 8 extension).
  - The first player in the room is the host; if the host disconnects, the
    remaining player is promoted automatically.
  - A player leaving mid-game returns the room to the lobby state and
    broadcasts game_aborted (reconnection is out of scope for Step 2).
  - Protocol errors are non-fatal: the server replies {"type": "error", ...}
    and keeps the socket open so clients can retry without reconnecting.
  - Ruleset players are registered under their lobby player ID (unique), so
    scores and turn identity map straight back to web players.
"""

from __future__ import annotations

import logging
import random
import string
import time
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from . import bridge, physics, rules

logger = logging.getLogger(__name__)


class LobbyError(Exception):
    """Protocol-level error; sent to the client as an error message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


CODE_LEN = 4
CODE_ALPHABET = string.ascii_uppercase
MAX_PLAYERS = 2
NAME_MAX_LEN = 24
LOBBY = "lobby"
PLAYING = "playing"
DEFAULT_MODE = rules.DEFAULT_MODE

# Step 10: solo practice mode ("Тренировка"). Deliberately NOT part of
# rules.MODES — it bypasses the vendored rulesets entirely (plain on-table
# state + lobby-level post-processing; see _finish_practice_shot), so the
# frozen-rules policy is untouched.
PRACTICE_MODE = "practice"
PRACTICE_MODE_NAME = "Practice («Тренировка»)"


@dataclass
class Player:
    id: str
    name: str
    ws: WebSocket


@dataclass
class Room:
    code: str
    players: list[Player] = field(default_factory=list)
    state: str = LOBBY
    # Step 6: selected discipline (host-set in the lobby, applied on start).
    mode: str = DEFAULT_MODE
    # Step 6: the live vendored ruleset instance (opaque here — driven via
    # app/rules.py + app/bridge.py). None until the game starts.
    game: object | None = None
    # Current on-table ball state (pocketed/removed balls excluded); a
    # fresh random rack is dealt on start_game and updated after every shot.
    balls: dict[str, dict[str, float]] = field(default_factory=dict)
    shot_seq: int = 0
    # Step 8: epoch ms when the current stroke's thinking time began (set on
    # start_game and refreshed with every shot_result broadcast).
    turn_started_ms: int = 0
    # Step 10: solo practice session state.
    practice: bool = False
    practice_bih: str = "none"  # live ball-in-hand grant for practice
    practice_last: dict | None = None  # last_shot block for the snapshot

    @property
    def host(self) -> Player | None:
        return self.players[0] if self.players else None

    def stamp_turn_clock(self, snapshot: dict) -> dict:
        """Add the Step 8 turn clock to a game snapshot (in place + returned).

        ``turn_started_ms`` — when thinking time for the upcoming stroke
        began; ``now_ms`` — server epoch at snapshot build time, letting
        clients correct for clock skew.
        """
        now_ms = int(time.time() * 1000)
        if not self.turn_started_ms:
            self.turn_started_ms = now_ms
        snapshot["turn_started_ms"] = self.turn_started_ms
        snapshot["now_ms"] = now_ms
        return snapshot

    def summary(self) -> dict:
        return {
            "code": self.code,
            "state": self.state,
            "mode": self.mode,
            "players": [
                {"id": p.id, "name": p.name, "is_host": p is self.host}
                for p in self.players
            ],
            "ball_count": len(self.balls),
        }


@dataclass
class Session:
    """A live WebSocket connection bound to a room membership."""

    room: Room
    player: Player


class LobbyManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    # -- queries -----------------------------------------------------------

    def get(self, code: str) -> Room | None:
        return self._rooms.get(code)

    def rooms(self) -> list[Room]:
        return list(self._rooms.values())

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _clean_name(raw: object) -> str:
        if not isinstance(raw, str):
            raise LobbyError("invalid_name", "name must be a string")
        name = raw.strip()[:NAME_MAX_LEN]
        if not name:
            raise LobbyError("invalid_name", "name must not be empty")
        return name

    @staticmethod
    def _clean_code(raw: object) -> str:
        if not isinstance(raw, str):
            raise LobbyError("room_not_found", "room code must be a string")
        code = raw.strip().upper()
        if len(code) != CODE_LEN or not all(c in CODE_ALPHABET for c in code):
            raise LobbyError("room_not_found", "room code must be 4 letters A-Z")
        return code

    def _new_code(self) -> str:
        while True:
            code = "".join(random.choices(CODE_ALPHABET, k=CODE_LEN))
            if code not in self._rooms:
                return code

    async def _send(self, player: Player, message: dict) -> None:
        try:
            await player.ws.send_json(message)
        except Exception:
            # Deliberately broad: the exact exception type raised by a send on
            # a dead socket depends on the ASGI/WS stack. A failed send is
            # never fatal here -- that player's own disconnect handler removes
            # them from the room.
            logger.debug("send to player %s failed", player.id, exc_info=True)

    async def _broadcast(self, room: Room, message: dict) -> None:
        for player in list(room.players):
            await self._send(player, message)

    async def _broadcast_player_list(self, room: Room) -> None:
        await self._broadcast(
            room,
            {
                "type": "player_list",
                "mode": room.mode,
                "players": room.summary()["players"],
            },
        )

    # -- protocol actions ----------------------------------------------------

    async def create_room(self, ws: WebSocket, msg: dict) -> Session:
        name = self._clean_name(msg.get("name"))
        room = Room(code=self._new_code())
        player = Player(id=uuid.uuid4().hex[:8], name=name, ws=ws)
        room.players.append(player)
        self._rooms[room.code] = room
        logger.info("room %s created by %s (%s)", room.code, name, player.id)
        session = Session(room=room, player=player)
        await self._send(
            player,
            {
                "type": "joined",
                "room": room.code,
                "player_id": player.id,
                "is_host": True,
                "mode": room.mode,
                "players": room.summary()["players"],
            },
        )
        return session

    async def join_room(self, ws: WebSocket, msg: dict) -> Session:
        code = self._clean_code(msg.get("room"))
        name = self._clean_name(msg.get("name"))
        room = self._rooms.get(code)
        if room is None:
            raise LobbyError("room_not_found", f"room {code} does not exist")
        if room.state == PLAYING:
            raise LobbyError("game_in_progress", f"room {code} is already playing")
        if len(room.players) >= MAX_PLAYERS:
            raise LobbyError(
                "room_full", f"room {code} already has {MAX_PLAYERS} players"
            )
        player = Player(id=uuid.uuid4().hex[:8], name=name, ws=ws)
        room.players.append(player)
        session = Session(room=room, player=player)
        logger.info("room %s joined by %s (%s)", room.code, name, player.id)
        await self._send(
            player,
            {
                "type": "joined",
                "room": room.code,
                "player_id": player.id,
                "is_host": False,
                "mode": room.mode,
                "players": room.summary()["players"],
            },
        )
        await self._broadcast_player_list(room)
        return session

    async def handle(self, session: Session, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "start_game":
            await self.start_game(session)
        elif kind == "set_mode":
            await self.set_mode(session, msg)
        elif kind == "shot":
            await self.shot(session, msg)
        elif kind == "place_cue":
            await self.place_cue(session, msg)
        elif kind == "practice":
            await self.practice(session)
        elif kind == "ping":
            await self._send(session.player, {"type": "pong"})
        else:
            raise LobbyError("invalid_message", f"unknown message type: {kind!r}")

    async def set_mode(self, session: Session, msg: dict) -> None:
        """Host picks the discipline while the room is in the lobby state."""
        room = session.room
        if room.host is not session.player:
            raise LobbyError("not_host", "only the host can pick the game mode")
        if room.state == PLAYING and not rules.is_game_finished(room.game):
            raise LobbyError("game_in_progress", "mode is fixed once the game started")
        mode = msg.get("mode")
        if not rules.is_valid_mode(mode):
            raise LobbyError(
                "invalid_mode",
                f"mode must be one of {sorted(rules.MODES)} (got {mode!r})",
            )
        room.mode = mode
        await self._broadcast_player_list(room)

    async def start_game(self, session: Session) -> None:
        """Deal a fresh game (also the rematch path once a game is over)."""
        room = session.room
        if room.host is not session.player:
            raise LobbyError("not_host", "only the host can start the game")
        finished = rules.is_game_finished(room.game)
        if room.state == PLAYING and not finished:
            raise LobbyError("game_in_progress", "game already started")
        if len(room.players) < 2:
            raise LobbyError("not_enough_players", "need 2 players to start")
        room.state = PLAYING
        room.balls = physics.russian_rack()  # fresh random rack, dealt once
        room.shot_seq = 0
        room.game = rules.new_game(room.mode, room.players)
        room.practice = False
        room.practice_bih = "none"
        room.practice_last = None
        room.turn_started_ms = 0  # stamped fresh by the snapshot helper below
        logger.info(
            "game started room=%s mode=%s players=%s",
            room.code, room.mode, [p.name for p in room.players],
        )
        await self._broadcast(
            room,
            {
                "type": "game_started",
                "mode": room.mode,
                "mode_name": rules.MODES[room.mode]["name"],
                "target_score": rules.MODES[room.mode]["target"],
                "players": room.summary()["players"],
                "balls": room.balls,
                "game": room.stamp_turn_clock(
                    rules.game_snapshot(room.mode, room.game, room.players)
                ),
            },
        )

    def _require_active_shooter(self, room: Room, session: Session) -> None:
        """Shared gate for shot/place_cue: playing, not over, shooter's turn."""
        if room.practice:
            # Step 10: practice has no ruleset and no turns — the solo player
            # (the host) may always shoot; joiners are soft-locked out.
            if room.state != PLAYING:
                raise LobbyError("not_playing", "start the practice session first")
            if room.host is not session.player:
                raise LobbyError(
                    "not_your_turn", f"practice is controlled by {room.host.name}"
                )
            return
        if room.state != PLAYING or room.game is None:
            raise LobbyError("not_playing", "start the game before shooting")
        if rules.is_game_finished(room.game):
            raise LobbyError(
                "game_over", "the game is over — the host can start a rematch"
            )
        active_id = room.game.active_player.name  # ruleset player name = id
        if active_id != session.player.id:
            active = next((p for p in room.players if p.id == active_id), None)
            who = active.name if active else active_id
            raise LobbyError("not_your_turn", f"it is {who}'s turn")

    def _apply_call(self, room: Room, msg: dict) -> None:
        """Classic («заказ») call intake: validate and write into the
        ruleset's current shot constraints (read by build_shot_info)."""
        constraints = room.game.shot_constraints
        if not constraints.call_shot:
            return  # this stroke needs no call; ignore any sent anyway
        ball_call = msg.get("ball_call")
        pocket_call = msg.get("pocket_call")
        if not isinstance(ball_call, str) or not isinstance(pocket_call, str):
            raise LobbyError(
                "invalid_call",
                "this stroke must be called: send 'ball_call' (object ball id) "
                "and 'pocket_call' (pocket id)",
            )
        if ball_call == "cue" or ball_call not in constraints.hittable:
            raise LobbyError(
                "invalid_call",
                f"called ball must be a live object ball (got {ball_call!r})",
            )
        if pocket_call not in rules.POCKET_IDS:
            raise LobbyError(
                "invalid_call",
                f"called pocket must be one of {sorted(rules.POCKET_IDS)} "
                f"(got {pocket_call!r})",
            )
        constraints.ball_call = ball_call
        constraints.pocket_call = pocket_call

    async def shot(self, session: Session, msg: dict) -> None:
        """Judge a client-simulated stroke from its terminal report (Step 11).

        The shooting client has ALREADY simulated the stroke locally and
        animated it; this handler only validates the report, reconstructs
        the synthetic ruleset input (``app/bridge.py``) and runs the frozen
        rulesets synchronously (microseconds — no physics, no worker thread,
        no "Simulating…" window). The broadcast carries the authoritative
        post-rules state for every client.
        """
        room = session.room
        self._require_active_shooter(room, session)
        if not room.practice:
            # Classic («заказ») call intake — ruleset modes only (practice has
            # no ruleset and thus no shot constraints to write into).
            self._apply_call(room, msg)

        pre_balls = {
            ball_id: {"x": float(pos["x"]), "y": float(pos["y"])}
            for ball_id, pos in room.balls.items()
        }
        try:
            report = bridge.parse_report(msg, set(pre_balls))
        except bridge.InvalidShot as exc:
            logger.info(
                "shot report rejected room=%s player=%s: %s",
                room.code, session.player.name, exc,
            )
            raise LobbyError("invalid_shot", str(exc)) from exc

        shooter = session.player
        shot_id = room.shot_seq + 1
        logger.info(
            "shot #%d report room=%s player=%s(%s) v0=%.2f phi=%.1f "
            "balls=%d pocketed=%s practice=%s",
            shot_id, room.code, shooter.name, shooter.id, report["v0"],
            report["phi"], len(pre_balls),
            [p["ball"] for p in report["pocketed"]], room.practice,
        )

        if room.practice:
            outcome = self._practice_outcome(room, report)
        else:
            try:
                outcome = bridge.apply_ruleset(report, pre_balls, room.game)
            except bridge.InvalidShot as exc:
                logger.warning(
                    "shot #%d rejected room=%s: %s", shot_id, room.code, exc,
                    exc_info=True,
                )
                raise LobbyError("invalid_shot", str(exc)) from exc
            except Exception as exc:  # defensive: report, keep everything alive
                logger.exception("shot #%d failed room=%s", shot_id, room.code)
                raise LobbyError(
                    "shot_failed", f"internal error: {exc}"
                ) from exc

        room.shot_seq = shot_id
        # Authoritative post-shot state: the ruleset has already respotted /
        # removed balls, so room.balls is exactly the on-table world.
        room.balls = outcome["balls"]
        # Step 8: thinking time for the upcoming stroke starts when the
        # verdict lands (also on legal continuations — the clock measures
        # per-stroke preparation, not per-turn ownership).
        room.turn_started_ms = int(time.time() * 1000)

        snapshot = (
            self._practice_snapshot(room)
            if room.practice
            else rules.game_snapshot(room.mode, room.game, room.players)
        )
        await self._broadcast(
            room,
            {
                "type": "shot_result",
                "shot_id": shot_id,
                "by": shooter.id,
                "by_name": shooter.name,
                "pocketed": outcome["pocketed"],
                "respotted": outcome["respotted"],
                "removed": outcome["removed"],
                "legal": outcome["legal"],
                "reason": outcome["reason"],
                "balls": room.balls,
                "judge_ms": outcome["judge_ms"],
                "game": room.stamp_turn_clock(snapshot),
            },
        )
        logger.info(
            "shot_result #%d broadcast room=%s legal=%s to %d player(s)",
            shot_id, room.code, outcome["legal"], len(room.players),
        )

    def _practice_outcome(self, room: Room, report: dict) -> dict:
        """Practice post-processing on plain dicts (the vendored rulesets
        stay frozen): potted balls leave the table, a scratch respots the
        cue at the deterministic house position and grants ball-in-hand
        anywhere; the solo player never loses the turn."""
        balls = {
            ball_id: {"x": x, "y": y}
            for ball_id, (x, y) in report["final"].items()
        }
        potted = [p["ball"] for p in report["pocketed"]]
        scratch = "cue" in potted
        if scratch:
            x, y = _practice_place_cue(balls)
            balls["cue"] = {"x": x, "y": y}
            room.practice_bih = "anywhere"
        else:
            room.practice_bih = "none"
        reason = (
            "scratch — cue respotted (ball in hand)" if scratch else "practice"
        )
        room.practice_last = {
            "legal": True,
            "reason": reason,
            "turn_over": False,
        }
        return {
            "balls": balls,
            "pocketed": potted,
            "respotted": [],
            "removed": [],  # planar client physics has no jumped balls
            "legal": True,
            "reason": reason,
            "judge_ms": 0.0,
        }

    def _practice_snapshot(self, room: Room) -> dict:
        """Wire snapshot for a practice session (same shape as ruleset
        snapshots, so the client HUD consumes it unchanged): no opponent,
        never game over, the solo player always owns the turn."""
        host = room.host
        return {
            "mode": PRACTICE_MODE,
            "mode_name": PRACTICE_MODE_NAME,
            "target_score": 0,
            "shot_number": room.shot_seq,
            "turn_number": room.shot_seq,
            "turn": {"id": host.id, "name": host.name},
            "scores": [{"id": host.id, "name": host.name, "score": 0}],
            "ball_in_hand": room.practice_bih,
            "call_shot": False,
            "hittable": [bid for bid in room.balls if bid != "cue"],
            "game_over": False,
            "winner": None,
            "last_shot": room.practice_last,
        }

    async def practice(self, session: Session) -> None:
        """Step 10: start (or re-rack) a solo practice session.

        Host-only, instant, works from an empty room ("Тренировка" from the
        lobby entry) or as a re-rack while a practice session is already
        running. The room stays code-addressable but a second player cannot
        join a session in progress (join is refused while PLAYING).
        """
        room = session.room
        if room.host is not session.player:
            raise LobbyError("not_host", "practice is controlled by the host")
        re_rack = room.state == PLAYING and room.practice
        if room.state == PLAYING and not re_rack:
            raise LobbyError(
                "game_in_progress", "finish the current game first"
            )
        room.state = PLAYING
        room.mode = PRACTICE_MODE
        room.practice = True
        room.balls = physics.russian_rack()
        room.shot_seq = 0
        room.game = None
        room.practice_bih = "none"
        room.practice_last = None
        room.turn_started_ms = 0
        logger.info(
            "practice session started room=%s player=%s (re_rack=%s)",
            room.code, session.player.name, re_rack,
        )
        await self._broadcast(
            room,
            {
                "type": "game_started",
                "mode": PRACTICE_MODE,
                "mode_name": PRACTICE_MODE_NAME,
                "target_score": 0,
                "practice": True,
                "players": room.summary()["players"],
                "balls": room.balls,
                "game": room.stamp_turn_clock(self._practice_snapshot(room)),
            },
        )

    async def place_cue(self, session: Session, msg: dict) -> None:
        """Ball-in-hand: the active player repositions the cue ball."""
        room = session.room
        self._require_active_shooter(room, session)
        if room.practice:
            bih = room.practice_bih
        else:
            constraints = room.game.shot_constraints
            bih = constraints.ball_in_hand.value
        if bih == "none":
            raise LobbyError("no_ball_in_hand", "no ball-in-hand privilege is active")
        others = {
            ball_id: (pos["x"], pos["y"])
            for ball_id, pos in room.balls.items()
            if ball_id != "cue"
        }
        try:
            x, y = rules.validate_cue_placement(bih, msg.get("x"), msg.get("y"), others)
        except (TypeError, ValueError) as exc:
            raise LobbyError("invalid_placement", str(exc))
        room.balls["cue"] = {"x": x, "y": y}
        logger.info(
            "cue placed room=%s by %s at (%.3f, %.3f) practice=%s",
            room.code, session.player.name, x, y, room.practice,
        )
        await self._broadcast(
            room,
            {
                "type": "cue_placed",
                "by": session.player.id,
                "by_name": session.player.name,
                "x": x,
                "y": y,
            },
        )

    async def leave(self, session: Session) -> None:
        room = session.room
        player = session.player
        if self._rooms.get(room.code) is not room:
            return  # room already deleted
        if player not in room.players:
            return  # already removed
        room.players.remove(player)
        if not room.players:
            del self._rooms[room.code]
            return
        if room.state == PLAYING:
            # The game cannot continue with one player; reconnection handling
            # is deferred to the game-integration steps.
            room.state = LOBBY
            room.game = None
            room.practice = False
            room.practice_bih = "none"
            room.practice_last = None
            await self._broadcast(
                room, {"type": "game_aborted", "reason": "player_left"}
            )
        await self._broadcast_player_list(room)


manager = LobbyManager()


def _practice_place_cue(balls: dict[str, dict[str, float]]) -> tuple[float, float]:
    """Deterministic house respot for a practice scratch — mirrors the
    vendored default policy on plain dicts: the head spot, nudged towards
    the head rail in ball-diameter steps until it neither overlaps another
    ball nor leaves the surface margin; a coarse grid scan as the fallback
    (the physics-level helper covers the whole length already, this only
    guards a pathological full-table cluster)."""
    plain = {bid: (p["x"], p["y"]) for bid, p in balls.items()}
    try:
        return physics.respot_cue_position(plain)
    except physics.PhysicsError:
        pass
    r = physics.BALL_R
    step = 2 * physics.BALL_R + 0.005
    y = physics.TABLE_L - r
    while y >= -physics.SURFACE_MARGIN:
        x = r
        while x <= physics.TABLE_W - r + 1e-9:
            if all(
                (x - bx) ** 2 + (y - by) ** 2 >= physics.MIN_SEPARATION**2
                for bx, by in plain.values()
            ):
                return x, y
            x += step
        y -= step
    return physics.TABLE_W / 2, 0.25 * physics.TABLE_L
