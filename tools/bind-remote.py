"""Authorise the handheld remote on the bulbs and bind it to them.

This is the step that makes the remote work without a hub in the command
path. Two writes per bulb-pair:

  1. Each bulb's Access Control List gains an entry granting the remote
     `Operate` privilege. Without it the bulbs reject the remote's CASE
     session - it is a fabric member, but an unauthorised one.
  2. The remote's Binding table is filled with one entry per (bulb, cluster)
     it should drive. Bindings are what turn a key press into a unicast
     command to a specific peer rather than nothing at all.

After this the remote talks straight to the bulbs over Thread. The
controller is needed only to perform these writes, never afterwards.

    uv run python tools/bind-remote.py --remote-node 13            # dry run
    uv run python tools/bind-remote.py --remote-node 13 --apply

The ACL write is the dangerous one: it replaces the whole list, so dropping
the existing administer entry would lock the controller out of that bulb
permanently and leave a factory reset as the only way back. Every existing
entry is therefore preserved and the result is verified by reading it back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])

from kajplats.matter import MatterBackend  # noqa: E402

# Access Control cluster 0x001F on the root endpoint; ACL is attribute 0.
ACL_PATH = "0/31/0"

# AccessControlEntryStruct field numbers.
F_PRIVILEGE = "1"
F_AUTH_MODE = "2"
F_SUBJECTS = "3"
F_TARGETS = "4"
F_FABRIC_INDEX = "254"

PRIVILEGE_OPERATE = 3
PRIVILEGE_ADMINISTER = 5
AUTH_MODE_CASE = 2

# Binding cluster 0x001E, attribute 0, on the remote's client endpoint.
BINDING_CLUSTER = 30

# Clusters the remote drives. ColorControl is included even though these are
# white-spectrum bulbs: the remote sends MoveToColorTemperature, which lives
# in ColorControl regardless of whether hue is supported.
CLUSTER_ON_OFF = 6
CLUSTER_LEVEL = 8
CLUSTER_COLOR = 768
BOUND_CLUSTERS = (CLUSTER_ON_OFF, CLUSTER_LEVEL, CLUSTER_COLOR)


def light_endpoints(node: dict) -> list[int]:
    """Endpoints on a node that expose an OnOff server, i.e. the lights."""
    endpoints = set()
    for path in (node.get("attributes") or {}):
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == str(CLUSTER_ON_OFF) and parts[0] != "0":
            endpoints.add(int(parts[0]))
    return sorted(endpoints)


def with_operate_entry(acl: list, remote_node: int) -> tuple[list, bool]:
    """Return the ACL plus an Operate grant for `remote_node`.

    Existing entries are kept verbatim. Returns (new_acl, changed).
    """
    acl = list(acl or [])

    for entry in acl:
        subjects = entry.get(F_SUBJECTS) or []
        if remote_node in subjects and entry.get(F_PRIVILEGE, 0) >= PRIVILEGE_OPERATE:
            return acl, False  # already authorised

    # Keep the fabric index of an existing entry: entries are fabric-scoped
    # and writing the wrong index would land the grant on another fabric.
    fabric_index = 1
    for entry in acl:
        if F_FABRIC_INDEX in entry:
            fabric_index = entry[F_FABRIC_INDEX]
            break

    acl.append({
        F_PRIVILEGE: PRIVILEGE_OPERATE,
        F_AUTH_MODE: AUTH_MODE_CASE,
        F_SUBJECTS: [remote_node],
        F_TARGETS: None,
        F_FABRIC_INDEX: fabric_index,
    })
    return acl, True


def bindings_for(targets: list[tuple[int, int]], fabric_index: int = 1) -> list:
    """One binding per (bulb node, endpoint, cluster)."""
    out = []
    for node_id, endpoint in targets:
        for cluster in BOUND_CLUSTERS:
            out.append({
                "1": node_id,       # Node
                "3": endpoint,      # Endpoint
                "4": cluster,       # Cluster
                "254": fabric_index,
            })
    return out


def has_administer(acl: list) -> bool:
    return any(e.get(F_PRIVILEGE) == PRIVILEGE_ADMINISTER for e in acl or [])


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--remote-node", type=int, required=True,
                    help="node id the remote was given at commissioning")
    ap.add_argument("--remote-endpoint", type=int, default=1,
                    help="the remote's client endpoint (default 1)")
    ap.add_argument("--url", default="ws://localhost:5580/ws")
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without it nothing is changed")
    args = ap.parse_args()

    backend = MatterBackend(args.url)
    backend.on_state(lambda *a: None)
    await backend.start()

    nodes = await backend._send("get_nodes", {"only_available": False})
    bulbs = [n for n in (nodes or [])
             if n.get("node_id") != args.remote_node and light_endpoints(n)]
    remote = next((n for n in (nodes or [])
                   if n.get("node_id") == args.remote_node), None)

    if not bulbs:
        print("no bulbs found on the fabric", file=sys.stderr)
        await backend.stop()
        return 1
    if remote is None:
        print(f"node {args.remote_node} is not on the fabric - commission the "
              f"remote first", file=sys.stderr)
        await backend.stop()
        return 1

    mode = "APPLY" if args.apply else "DRY RUN (nothing will be written)"
    print(f"=== {mode} ===\n")

    targets: list[tuple[int, int]] = []
    planned: list[tuple[int, list]] = []

    for bulb in bulbs:
        node_id = bulb["node_id"]
        endpoints = light_endpoints(bulb)
        targets.extend((node_id, ep) for ep in endpoints)

        current = (bulb.get("attributes") or {}).get(ACL_PATH) or []
        updated, changed = with_operate_entry(current, args.remote_node)

        print(f"bulb node {node_id}  (light endpoints: {endpoints})")
        print(f"  current ACL: {json.dumps(current)}")
        if not changed:
            print("  already grants the remote Operate - leaving alone\n")
            continue
        if not has_administer(updated):
            print("  REFUSING: result would have no Administer entry, which "
                  "would lock the controller out\n", file=sys.stderr)
            await backend.stop()
            return 1
        print(f"  new ACL:     {json.dumps(updated)}")
        print(f"  (+1 entry: Operate/CASE for node {args.remote_node})\n")
        planned.append((node_id, updated))

    binding = bindings_for(targets)
    print(f"remote node {args.remote_node}, endpoint {args.remote_endpoint}")
    print(f"  binding table: {len(binding)} entries "
          f"({len(targets)} target(s) x {len(BOUND_CLUSTERS)} clusters)")
    for entry in binding:
        print(f"    node {entry['1']} ep {entry['3']} cluster {entry['4']}")

    if not args.apply:
        print("\nre-run with --apply to write this.")
        await backend.stop()
        return 0

    print("\n--- writing ---")
    for node_id, acl in planned:
        await backend._send("write_attribute", {
            "node_id": node_id, "attribute_path": ACL_PATH, "value": acl,
        })
        print(f"  node {node_id}: ACL written")

    await backend._send("write_attribute", {
        "node_id": args.remote_node,
        "attribute_path": f"{args.remote_endpoint}/{BINDING_CLUSTER}/0",
        "value": binding,
    })
    print(f"  node {args.remote_node}: binding table written")

    # Read back rather than trusting the write: a silently rejected ACL write
    # is the difference between a working remote and an afternoon of
    # debugging the radio.
    print("\n--- verifying ---")
    ok = True
    for node_id, _ in planned:
        acl = await backend._send("read_attribute", {
            "node_id": node_id, "attribute_path": ACL_PATH,
        })
        entries = acl if isinstance(acl, list) else (acl or {}).get(ACL_PATH, [])
        granted = any(args.remote_node in (e.get(F_SUBJECTS) or [])
                      for e in (entries or []))
        print(f"  node {node_id}: remote authorised = {granted}")
        ok = ok and granted

    await backend.stop()
    if ok:
        print("\nDone. The remote can now command the bulbs directly.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
