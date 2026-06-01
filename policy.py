from dataclasses import dataclass

@dataclass(frozen=True)
class SandboxPolicy:
    allow_read: bool = True
    allow_write: bool = False
    allow_network: bool = False
    allow_shell: bool = False

@dataclass(frozen=True)
class ApprovalPolicy:
    # "never": never ask for approval; deny if the sandbox policy does not allow the capability
    # "on_request": ask the user when a tool needs a capability outside the sandbox policy
    # "untrusted": ask for approval when the tool call has high risk (e.g. write or network)
    mode : str = "on_request" 


@dataclass(frozen=True)
class PolicyDecision:
    action: str # "allow" / "deny" / "ask"
    reason: str = ""


def check_policy(tool_spec, sandbox_policy, approval_policy):
    capability = tool_spec.capability

    allowed = {
        "read": sandbox_policy.allow_read,
        "write": sandbox_policy.allow_write,
        "network": sandbox_policy.allow_network,
        "shell": sandbox_policy.allow_shell,
    }.get(capability, False)

    if allowed:
        if approval_policy.mode == "untrusted" and capability in (
            "write", "network", "shell"):
            return PolicyDecision(
                action="ask", 
                reason=f"Tool '{tool_spec.name}' needs capability '{capability}' which is considered high risk. Approval is required.")
        return PolicyDecision(action="allow")
    
    if approval_policy.mode in {"on_request", "untrusted"}:
        return PolicyDecision(
            action="ask", 
            reason=f"Tool '{tool_spec.name}' needs capability '{capability}', which is not allowed by the sandbox policy. Approval is required to execute.")
    
    return PolicyDecision(
        action="deny",
        reason=f"Tool '{tool_spec.name}' needs capability '{capability}', but sandbox policy does not allow it and approval policy does not allow asking for approval."
    )


def read_only_policy():
    return (
        SandboxPolicy(
            allow_read=True,
            allow_write=False,
            allow_network=False,
            allow_shell=False,
        ),
        ApprovalPolicy(mode="never"),
    )


def interactive_policy():
    return (
        SandboxPolicy(
            allow_read=True,
            allow_write=False,
            allow_network=False,
            allow_shell=False,
        ),
        ApprovalPolicy(mode="on_request"),
    )


def workspace_policy():
    return (
        SandboxPolicy(
            allow_read=True,
            allow_write=True,
            allow_network=False,
            allow_shell=False,
        ),
        ApprovalPolicy(mode="on_request"),
    )
