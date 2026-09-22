from jarvis import agent, policy
from jarvis.capabilities import Capability, Risk, default_registry
from typesafe_computer_use import config


def test_registry_matches_the_criteria_agent_hands_to_jev():
    reg = default_registry()
    assert reg.criteria(group="open_app") == agent.app_criteria()
    from jarvis import system

    assert reg.criteria(group="system") == system.COMMANDS
    assert set(config.APPS) == {c.arg for c in reg.group("open_app")}


def test_registry_filters_by_risk_and_gui():
    reg = default_registry()
    read_only = reg.criteria(max_risk=Risk.READ, gui=False)
    assert set(read_only) == {"nothing", "notify.speak", "notify.toast"}
    assert all(c.gui for c in reg.group("open_app"))
    assert reg.get("system.lock").risk == Risk.MEDIUM
    assert reg.get("system.volume_up").risk == Risk.LOW
    reg.add(Capability("x.hidden", "no", Risk.READ, available=False))
    assert "x.hidden" not in reg.criteria()


def test_policy_table():
    speak = Capability("notify.speak", "say", Risk.READ)
    volume = Capability("system.volume_up", "up", Risk.LOW)
    lock = Capability("system.lock", "lock", Risk.MEDIUM)
    pay = Capability("web.pay", "pay", Risk.HIGH)
    open_app = Capability("open_app.notepad", "open", Risk.LOW, gui=True)
    gone = Capability("x", "x", Risk.READ, available=False)
    remote = Capability("phone.ring", "ring", Risk.LOW, device="phone")

    idle = policy.Context(user_active=False)
    active = policy.Context(user_active=True)
    asked = policy.Context(user_active=True, foreground_ok=True)

    assert policy.authorize(speak, ctx=active).decision == policy.ALLOW
    assert policy.authorize(volume, ctx=active).decision == policy.ALLOW
    assert policy.authorize(lock, ctx=idle).decision == policy.ASK
    assert policy.authorize(pay, ctx=asked).decision == policy.ASK
    assert policy.authorize(gone, ctx=idle).decision == policy.DENY
    assert policy.authorize(remote, ctx=idle).decision == policy.DENY
    # the presence gate: GUI work is denied while the person types, unless they asked, or they are away
    assert policy.authorize(open_app, ctx=active).decision == policy.DENY
    assert policy.authorize(open_app, ctx=policy.Context()).decision == policy.DENY  # unknown presence counts as active
    assert policy.authorize(open_app, ctx=asked).decision == policy.ALLOW
    assert policy.authorize(open_app, ctx=idle).decision == policy.ALLOW
    assert bool(policy.authorize(speak)) and not bool(policy.authorize(lock))


def test_step_gate_is_the_existing_gate():
    from jarvis.gates import Confirmer, Gate

    gate = policy.step_gate(object(), Confirmer(ask=lambda q: None))
    assert isinstance(gate, Gate)
