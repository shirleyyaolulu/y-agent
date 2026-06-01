from policy import check_policy, read_only_policy, interactive_policy
from tool_registry import TOOL_REGISTRY

def test_read_only_denies_write():
    sandbox, approval = read_only_policy()
    decision = check_policy(TOOL_REGISTRY["save_note"], sandbox, approval)
    print(decision.action)
    assert decision.action == "deny"


def test_interactive_asks_for_write():
    sandbox, approval = interactive_policy()
    decision = check_policy(TOOL_REGISTRY["save_note"], sandbox, approval) 
    print(decision.action)
    assert decision.action == "ask"


def test_read_is_allowed():
    sandbox, approval = interactive_policy()
    decision = check_policy(TOOL_REGISTRY["get_time"], sandbox, approval)
    print(decision.action)
    assert decision.action == "allow"

test_read_only_denies_write()
test_interactive_asks_for_write()
test_read_is_allowed()