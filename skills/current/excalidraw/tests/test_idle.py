"""Idle-shutdown decisions and canvas health parsing for the watchdog."""

import pytest

from cli import Action, Health, Observation, WatchState, decide, parse_health

IDLE = 1800.0
START = 1_000.0


def state(*, scene: str = "s0", last_activity: float = START) -> WatchState:
    return WatchState(server_pid=42, scene_hash=scene, last_activity=last_activity)


def seen(
    *,
    pid: int = 42,
    tabs: int = 0,
    scene: str = "s0",
    last_used: float = 0.0,
) -> Observation:
    return Observation(
        server_pid=pid,
        browser_tabs=tabs,
        elements=1,
        scene_hash=scene,
        last_used=last_used,
    )


def test_untouched_server_stops_once_idle_window_elapses():
    action, _ = decide(state(), seen(), now=START + IDLE, idle_seconds=IDLE)
    assert action is Action.STOP


def test_untouched_server_survives_just_before_the_window():
    action, updated = decide(state(), seen(), now=START + IDLE - 1, idle_seconds=IDLE)
    assert action is Action.KEEP
    assert updated == state()


def test_open_browser_tab_keeps_server_alive_indefinitely():
    action, updated = decide(
        state(), seen(tabs=1), now=START + 10 * IDLE, idle_seconds=IDLE
    )
    assert action is Action.KEEP
    assert updated.last_activity == START + 10 * IDLE


def test_scene_change_resets_the_idle_clock():
    now = START + IDLE + 5
    action, updated = decide(state(), seen(scene="s1"), now=now, idle_seconds=IDLE)
    assert action is Action.KEEP
    assert updated == state(scene="s1", last_activity=now)
    later, _ = decide(updated, seen(scene="s1"), now=now + IDLE - 1, idle_seconds=IDLE)
    assert later is Action.KEEP
    idle, _ = decide(updated, seen(scene="s1"), now=now + IDLE, idle_seconds=IDLE)
    assert idle is Action.STOP


def test_read_only_agent_command_counts_as_activity():
    used_at = START + IDLE - 10
    action, _ = decide(
        state(), seen(last_used=used_at), now=START + IDLE, idle_seconds=IDLE
    )
    assert action is Action.KEEP


def test_wrapper_use_counts_from_when_it_ran_not_when_polled():
    used_at = START + 100
    action, updated = decide(
        state(), seen(last_used=used_at), now=used_at + IDLE, idle_seconds=IDLE
    )
    assert action is Action.STOP
    assert updated.last_activity == used_at


def test_watchdog_exits_when_server_is_gone():
    action, _ = decide(state(), None, now=START + 1, idle_seconds=IDLE)
    assert action is Action.EXIT


def test_watchdog_exits_when_a_different_server_took_the_port():
    action, _ = decide(state(), seen(pid=99), now=START + 1, idle_seconds=IDLE)
    assert action is Action.EXIT


def test_zero_timeout_never_stops():
    action, _ = decide(state(), seen(), now=START + 100 * IDLE, idle_seconds=0)
    assert action is Action.KEEP


def test_parse_health_reads_the_canvas_server():
    body = {
        "status": "healthy",
        "service": "mcp-excalidraw-canvas",
        "pid": 73786,
        "websocket_clients": 2,
        "elements_count": 5,
    }
    assert parse_health(body) == Health(pid=73786, browser_tabs=2, elements=5)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(None, id="unreachable"),
        pytest.param(
            {
                "service": "something-else",
                "pid": 1,
                "websocket_clients": 0,
                "elements_count": 0,
            },
            id="foreign-service-on-port",
        ),
        pytest.param({"service": "mcp-excalidraw-canvas"}, id="missing-fields"),
        pytest.param(
            {
                "service": "mcp-excalidraw-canvas",
                "pid": True,
                "websocket_clients": 0,
                "elements_count": 0,
            },
            id="bool-pid",
        ),
        pytest.param([], id="not-an-object"),
    ],
)
def test_parse_health_rejects_anything_but_the_canvas_server(body: object):
    assert parse_health(body) is None
