"""
Homo Sui Iuris / Free Cognitive Protocol — integration layer wiring
NodeTransport (real network hop via bootstrap_relay.py) to
LeukocyteAgent + UpdateLoop (local Core Engine / Erythrocyte / Leukocyte
logic).

This replaces P2PNetworkSimulation.broadcast_antigen() from the
in-process demo (leukocyte_protocol.py, run_network_demo()) with a real
network hop, while leaving detection and blocking logic itself
completely untouched: this module is glue, not new immune-system logic.

Flow:
  local oscillating finding -> self-vaccinate (sync, in-process) ->
      broadcast_antigen over the network (async, fire-and-forget)
  antigen arrives over the network -> agent.register_antigen() locally

Connection lifecycle: delegated entirely to NodeTransport.run_forever(),
which owns reconnect + exponential backoff. This module no longer
manages its own heartbeat/flush/listener tasks — it just supplies the
on_antigen callback and lets the transport drive the session lifecycle.
connect() still awaits the FIRST successful handshake (via
transport.wait_connected()) so startup failures surface immediately,
same as before; every reconnect after that happens silently in the
background per the transport's backoff policy.

KNOWN LIMITATION — this used to be carried over unchanged from
run_network_demo() as a hardcoded placeholder hash. It no longer is:
this module now builds antigen signatures from finding["observed_contexts"]
(erythrocyte.collect_observed_contexts), which requires that whatever
calls CriticalityMatrix.update() for a suspicious write also passes a
real `context=` value. If a caller doesn't (e.g. legacy code that
hasn't been updated), the finding's observed_contexts list is empty,
and this module now broadcasts NO antigen rather than fabricating one
from a placeholder — an honest "no real data to fingerprint" is better
than a plausible-looking fake, per the project's stance against
illusory coverage.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, Optional

from core_engine import (
    ApprovalChannel,
    AuditLog,
    CriticalityMatrix,
    Model,
    ThresholdStrategy,
    UpdateLoop,
    Weight,
)
from leukocyte_protocol import AntigenSignature, LeukocyteAgent
from node_transport import AuthenticationError, NodeTransport

log = logging.getLogger("networked_node")

DEFAULT_CONNECT_TIMEOUT = 15.0  # seconds to wait for the FIRST handshake at startup


class NetworkedLeukocyteNode:
    """
    One testnet participant: local Core Engine + Erythrocyte + Leukocyte,
    connected to the bootstrap relay for antigen propagation and log
    upload. Everything except the network hop is the same code path
    run_network_demo() exercises in-process.
    """

    def __init__(
        self,
        node_id: str,
        relay_url: str,
        token: str,
        matrix: CriticalityMatrix,
        strategy: ThresholdStrategy,
        model: Model,
        approval_channel: ApprovalChannel,
        audit_log: AuditLog,
        verbose: bool = False,
        log_flush_interval: float = 15.0,
        heartbeat_interval: float = 30.0,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        on_disconnected: Optional[Any] = None,
        on_reconnecting: Optional[Any] = None,
        on_reconnected: Optional[Any] = None,
    ) -> None:
        self.node_id = node_id
        self.transport = NodeTransport(relay_url, node_id, token)
        self.agent = LeukocyteAgent(node_id=node_id)
        self.loop = UpdateLoop(
            matrix=matrix,
            strategy=strategy,
            model=model,
            approval_channel=approval_channel,
            audit_log=audit_log,
            verbose=verbose,
            erythrocyte_enabled=True,
        )
        # Same hook run_network_demo() overrides, for the same reason:
        # an oscillating finding must both correct locally AND propagate.
        self.loop._escalate_erythrocyte_finding = self._on_local_oscillating_finding

        self._log_flush_interval = log_flush_interval
        self._heartbeat_interval = heartbeat_interval
        self._connect_timeout = connect_timeout
        self._on_disconnected = on_disconnected
        self._on_reconnecting = on_reconnecting
        self._on_reconnected = on_reconnected
        self._run_forever_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Starts the transport's run_forever() loop in the background
        and waits for the first successful handshake. If the relay is
        unreachable or the token is rejected right away, this raises —
        same contract callers relied on before. Every reconnect after
        this point is handled silently by the transport."""
        self._run_forever_task = asyncio.create_task(
            self.transport.run_forever(
                on_antigen=self._on_network_antigen,
                heartbeat_interval=self._heartbeat_interval,
                flush_interval=self._log_flush_interval,
                on_disconnected=self._on_disconnected,
                on_reconnecting=self._on_reconnecting,
                on_reconnected=self._on_reconnected,
            )
        )
        # Race "first handshake succeeded" against "run_forever gave up
        # already" (e.g. AuthenticationError, which is not retried) —
        # waiting on wait_connected() alone would sit for the full
        # timeout even when the real answer is already known.
        wait_connected_task = asyncio.create_task(self.transport.wait_connected())
        done, _pending = await asyncio.wait(
            {wait_connected_task, self._run_forever_task},
            timeout=self._connect_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if wait_connected_task in done:
            return  # handshake succeeded — run_forever_task keeps running in the background
        wait_connected_task.cancel()
        if self._run_forever_task in done:
            self._run_forever_task.result()  # re-raises AuthenticationError (or whatever else)
            return
        # Neither finished within connect_timeout — first attempt is just slow/hanging.
        self._run_forever_task.cancel()
        raise ConnectionError(
            f"[{self.node_id}] no successful handshake with relay within {self._connect_timeout}s"
        )

    async def close(self) -> None:
        if self._run_forever_task is not None:
            self._run_forever_task.cancel()
            try:
                await self._run_forever_task
            except asyncio.CancelledError:
                pass
            except AuthenticationError:
                pass  # already logged when it first happened
        await self.transport.flush_logs()  # best-effort final flush
        await self.transport.close()

    # ------------------------------------------------------------------
    # Inbound: network antigen -> local agent
    # ------------------------------------------------------------------
    async def _on_network_antigen(self, payload: Dict[str, Any]) -> None:
        antigen = AntigenSignature(
            target_weight=payload.get("target_weight", ""),
            distortion_type=payload.get("distortion_type", ""),
            signature_hash=payload.get("signature_hash", ""),
        )
        self.agent.register_antigen(antigen)
        self.transport.queue_log({
            "event": "antigen_received",
            "node_id": self.node_id,
            "target_weight": antigen.target_weight,
        })
        log.info("[%s] received antigen for '%s' over network", self.node_id, antigen.target_weight)

    # ------------------------------------------------------------------
    # Outbound: local oscillating finding -> self-vaccinate + broadcast
    # ------------------------------------------------------------------
    def _on_local_oscillating_finding(self, finding: dict, weight_obj: Weight) -> None:
        # 1. Local baseline correction — happens regardless of whether
        # there's anything real to fingerprint below.
        self.loop.matrix.update(finding["weight"], weight_obj.baseline, source="erythrocyte_correction")

        # 2. Build one antigen per distinct payload Erythrocyte actually
        # observed for this weight — not a combined hash of all of them
        # (that would never match should_block()'s per-payload hash for
        # any single future attempt), and not a placeholder.
        observed_contexts = finding.get("observed_contexts", [])
        if not observed_contexts:
            log.warning(
                "[%s] oscillating finding on '%s' has no observed_contexts — "
                "corrected locally, but broadcasting NO antigen (nothing "
                "real to fingerprint; whatever wrote this weight never "
                "passed context= to CriticalityMatrix.update()).",
                self.node_id, finding["weight"],
            )
            self.transport.queue_log({
                "event": "escalation_without_fingerprint",
                "node_id": self.node_id,
                "target_weight": finding["weight"],
            })
            return

        for ctx in observed_contexts:
            signature_hash = hashlib.sha256(ctx.encode("utf-8")).hexdigest()
            antigen = AntigenSignature(
                target_weight=finding["weight"],
                distortion_type=finding["distortion"],
                signature_hash=signature_hash,
            )
            # Self-vaccinate synchronously — mirrors the in-process
            # broadcast_antigen()'s self-vaccination step. This does NOT
            # wait for the network round trip, so a node keeps
            # protecting itself even if the relay connection is briefly
            # down (or mid-reconnect).
            self.agent.register_antigen(antigen)
            # Propagate to the network. Scheduled as a task because this
            # hook is invoked synchronously from inside UpdateLoop.step()
            # (which is not itself async) — it cannot simply `await` here.
            asyncio.create_task(self._broadcast_antigen(antigen))
            self.transport.queue_log({
                "event": "antigen_escalated",
                "node_id": self.node_id,
                "target_weight": antigen.target_weight,
            })

        log.info(
            "[%s] local oscillating finding on '%s' -> self-vaccinated + broadcasting %d real antigen(s)",
            self.node_id, finding["weight"], len(observed_contexts),
        )

    async def _broadcast_antigen(self, antigen: AntigenSignature) -> None:
        try:
            await self.transport.send_antigen({
                "target_weight": antigen.target_weight,
                "distortion_type": antigen.distortion_type,
                "signature_hash": antigen.signature_hash,
            })
        except Exception:
            # If the relay connection is mid-reconnect, this antigen is
            # simply lost — not queued/retried. Self-vaccination above
            # already protects THIS node regardless; a lost broadcast
            # only delays other nodes learning about it, and the next
            # oscillation (if the attack repeats) will try again.
            log.exception("[%s] failed to broadcast antigen for '%s'", self.node_id, antigen.target_weight)

    # ------------------------------------------------------------------
    # Local attack surface: what a driving script calls per simulated step
    # ------------------------------------------------------------------
    def should_block(self, weight_name: str, simulated_payload: str) -> bool:
        blocked = self.agent.should_block(weight_name, simulated_payload)
        if blocked:
            self.transport.queue_log({
                "event": "attack_blocked",
                "node_id": self.node_id,
                "weight": weight_name,
            })
        return blocked

    def step(self, error: float, actual: float) -> None:
        self.loop.step(error=error, actual=actual)