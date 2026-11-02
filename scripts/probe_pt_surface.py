"""Probe pooltool API surface for the client-physics terminal-state bridge."""
import sys

sys.path.insert(0, "/home/z/my-project/pyramid-web/backend")

import attrs
import numpy as np

import pooltool as pt
import pooltool.constants as const
from pooltool.objects.table.collection import TABLE_SPECS, TableName
from pooltool.events.datatypes import Event, EventType, AgentType, Agent

spec = TABLE_SPECS[TableName.RUSSIAN_PYRAMID_GENERIC]
table = pt.Table.from_table_specs(spec)

print("POCKET IDS:", sorted(table.pockets.keys()))
for pid, p in table.pockets.items():
    print(f"  {pid}: center=({float(p.a):.4f},{float(p.b):.4f}) r={float(p.radius):.4f} "
          f"depth={float(p.depth):.4f} center_attr={getattr(p, 'center', None)}")

print("LINEAR CUSHION SEGMENTS:")
for cid, seg in table.cushion_segments.linear.items():
    print(f"  {cid}: p1={tuple(round(float(v),4) for v in seg.p1[:2])} p2={tuple(round(float(v),4) for v in seg.p2[:2])}")
print("CIRCULAR (jaw) SEGMENTS:")
for cid, seg in table.cushion_segments.circular.items():
    print(f"  {cid}: center={tuple(round(float(v),4) for v in seg.center[:2])} radius={float(seg.radius):.4f}")

print("const.stationary =", const.stationary, "state_dict:", const.state_dict[const.stationary])
print("const.pocketed   =", const.pocketed, "state_dict:", const.state_dict[const.pocketed])
print("const.on_table   =", const.on_table, "->", [const.state_dict[s] for s in const.on_table])
print("const.spinning   =", const.spinning, "sliding:", const.sliding, "rolling:", const.rolling)

# Ball construction with explicit state
ball = pt.Ball.create("5", xy=(0.5, 1.0), ballset=None, R=0.0335, m=0.28)
print("Ball created:", ball.id, "state s:", ball.state.s, "rvw:", ball.state.rvw[0])

# history API
from pooltool.objects.ball.datatypes import BallState
ball.history.add(BallState(rvw=ball.state.rvw.copy(), s=ball.state.s, t=0.0))
print("history len:", len(ball.history), "ts:", ball.history.ts)

# Event construction: check constructor signatures
import inspect
print("Event sig:", inspect.signature(Event))
print("Agent sig:", inspect.signature(Agent))

b1 = pt.Ball.create("cue", xy=(0.9, 0.85), ballset=None, R=0.0335, m=0.28)
ev = Event(
    event_type=EventType.BALL_BALL,
    time=0.42,
    agents=(Agent("cue", AgentType.BALL), Agent("5", AgentType.BALL)),
)
print("event ok:", ev.event_type, ev.time, [a.id for a in ev.agents])

print("AgentType members:", list(AgentType))
print("EventType BALL_BALL:", EventType.BALL_BALL,
      "| BALL_POCKET:", EventType.BALL_POCKET,
      "| BALL_LINEAR_CUSHION:", EventType.BALL_LINEAR_CUSHION,
      "| BALL_CIRCULAR_CUSHION:", EventType.BALL_CIRCULAR_CUSHION,
      "| BALL_OFF_TABLE:", EventType.BALL_OFF_TABLE)

# BallParams for russian
params = pt.BallParams.prebuilt(pt.PrebuiltBallParams.RUSSIAN_PYRAMID_GENERIC)
print("russian ball params: R =", params.R, "m =", params.m)

# HOUSE_LINE_FRACTION
from pooltool.ruleset.russian_pyramid import HOUSE_LINE_FRACTION
print("HOUSE_LINE_FRACTION =", HOUSE_LINE_FRACTION)
