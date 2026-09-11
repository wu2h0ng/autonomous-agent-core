/**
 * Spike Ink TUI: token-level streaming renderer over the surface protocol.
 *
 * Scope (queue A#1 spike): open/resume a session, subscribe-first, begin-turn,
 * render CHUNK frames as they arrive (typewriter), explicit GAP honesty,
 * permission-mode display, digest-bound approval card, Ctrl-C correction.
 * Not in scope: full slash-command set, markdown rendering, checkpoints.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, useApp, useInput } from "ink";
import TextInput from "ink-text-input";
import type { SurfaceClient } from "./client.js";
import { SurfaceStreamStaleError } from "./client.js";
import type {
  PermissionMode,
  SurfaceSessionSnapshot,
  SurfaceStreamBinding,
} from "./contracts.js";

interface ChatLine {
  role: "user" | "assistant" | "system";
  text: string;
}

type Phase = "idle" | "streaming" | "awaiting-approval" | "stalled";

const MODE_ORDER: PermissionMode[] = ["ASK", "ACCEPT_READ_ONLY", "ACCEPT_IN_WORKSPACE"];

export function App({ client, resumeSessionId }: { client: SurfaceClient; resumeSessionId?: string }) {
  const { exit } = useApp();
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [input, setInput] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [snapshot, setSnapshot] = useState<SurfaceSessionSnapshot | null>(null);
  const [stream, setStream] = useState<SurfaceStreamBinding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const sessionId = useRef<string | null>(resumeSessionId ?? null);

  const push = useCallback((line: ChatLine) => {
    setLines((prev) => [...prev, line]);
  }, []);

  const appendAssistant = useCallback((delta: string) => {
    setLines((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") {
        next[next.length - 1] = { ...last, text: last.text + delta };
      } else {
        next.push({ role: "assistant", text: delta });
      }
      return next;
    });
  }, []);

  const ensureStream = useCallback(
    async (sid: string): Promise<SurfaceStreamBinding> => {
      if (stream) return stream;
      const subscription = await client.subscribeStream(sid);
      const binding: SurfaceStreamBinding = {
        runtime_boot_id: subscription.runtime_boot_id,
        stream_id: subscription.stream_id,
      };
      setStream(binding);
      return binding;
    },
    [client, stream],
  );

  useEffect(() => {
    if (resumeSessionId) {
      client
        .getSession(resumeSessionId)
        .then((snap) => {
          setSnapshot(snap);
          push({ role: "system", text: `resumed session ${snap.session.session_id} (status ${snap.status}, mode ${snap.permission_mode})` });
        })
        .catch((cause) => setError((cause as Error).message));
    }
  }, [client, resumeSessionId, push]);

  const runTurn = useCallback(
    async (text: string) => {
      if (busy.current) return;
      busy.current = true;
      setError(null);
      try {
        let sid = sessionId.current;
        if (!sid) {
          const opened = await client.openSession("cli-ts spike session");
          sid = opened.session.session_id;
          sessionId.current = sid;
          setSnapshot(opened);
          push({ role: "system", text: `session ${sid} opened` });
        }
        const binding = await ensureStream(sid);
        push({ role: "user", text });
        setPhase("streaming");
        const begin = await client.beginTurn(sid, text, binding);
        for await (const frame of client.followStream(sid, binding)) {
          if (frame.kind === "CHUNK") {
            const delta = (frame.payload as { delta?: string }).delta ?? "";
            appendAssistant(delta);
          } else if (frame.kind === "GAP") {
            push({ role: "system", text: `[gap: frames ${frame.gap_from}–${frame.gap_to} lost; content not fabricated]` });
          } else if (frame.kind === "STREAM_END") {
            break;
          }
          void begin;
        }
        const finalSnap = await client.getSession(sid);
        setSnapshot(finalSnap);
        setStream(null);
        if (finalSnap.status === "WAITING_APPROVAL" && finalSnap.pending_approval) {
          setPhase("awaiting-approval");
        } else {
          setPhase("idle");
        }
      } catch (cause) {
        if (cause instanceof SurfaceStreamStaleError) {
          setStream(null);
          setError("stream generation stale; resubscribe on next turn");
        } else {
          setError((cause as Error).message);
        }
        setPhase("idle");
      } finally {
        busy.current = false;
      }
    },
    [appendAssistant, client, ensureStream, push],
  );

  const cycleMode = useCallback(async () => {
    const sid = sessionId.current;
    if (!sid || !snapshot || busy.current) return;
    const next = MODE_ORDER[(MODE_ORDER.indexOf(snapshot.permission_mode) + 1) % MODE_ORDER.length]!;
    try {
      const updated = await client.setPermissionMode(sid, next);
      setSnapshot(updated);
      push({ role: "system", text: `permission mode → ${next}` });
    } catch (cause) {
      setError((cause as Error).message);
    }
  }, [client, push, snapshot]);

  const decide = useCallback(
    async (disposition: "APPROVE" | "REJECT") => {
      const sid = sessionId.current;
      const pending = snapshot?.pending_approval;
      if (!sid || !pending) return;
      try {
        const turn = await client.decideApproval(sid, pending.action_digest, disposition, `${disposition.toLowerCase()} via cli-ts`);
        setSnapshot(turn.snapshot);
        push({ role: "system", text: `${disposition}: ${pending.capability_id}` });
        setPhase("idle");
      } catch (cause) {
        setError((cause as Error).message);
      }
    },
    [client, push, snapshot],
  );

  useInput((keyInput, key) => {
    if (key.ctrl && keyInput === "c") {
      const sid = sessionId.current;
      if (sid && busy.current) {
        void client.correct(sid, "operator interrupt (ctrl-c)").finally(() => exit());
      } else {
        exit();
      }
      return;
    }
    if (key.tab && key.shift) {
      void cycleMode();
      return;
    }
    if (phase === "awaiting-approval") {
      if (keyInput === "y") void decide("APPROVE");
      if (keyInput === "n") void decide("REJECT");
    }
  });

  const pending = snapshot?.pending_approval;

  return (
    <Box flexDirection="column">
      {lines.map((line, index) => (
        <Text key={index} color={line.role === "user" ? "cyan" : line.role === "system" ? "yellow" : "white"}>
          {line.role === "user" ? "> " : line.role === "system" ? "⏵ " : ""}
          {line.text}
        </Text>
      ))}
      {phase === "streaming" && <Text dimColor>streaming… (turn bound, frames live)</Text>}
      {phase === "awaiting-approval" && pending && (
        <Box flexDirection="column" borderStyle="round" borderColor="yellow">
          <Text bold>approval required — {pending.capability_id}</Text>
          <Text wrap="wrap">{pending.preview}</Text>
          <Text dimColor>digest {pending.action_digest.slice(0, 16)}… [y] approve [n] reject</Text>
        </Box>
      )}
      {error && <Text color="red">error: {error}</Text>}
      <Box>
        <Text color="green">{phase === "idle" ? "> " : "… "}</Text>
        <TextInput value={input} onChange={setInput} onSubmit={(value) => {
          const text = value.trim();
          setInput("");
          if (text === "/exit") { exit(); return; }
          if (text) void runTurn(text);
        }} />
      </Box>
      <Text dimColor>
        {snapshot ? `mode ${snapshot.permission_mode} · status ${snapshot.status} · events ${snapshot.event_sequence}` : "no session"}
        {" · shift+tab mode · ctrl-c correct/exit"}
      </Text>
    </Box>
  );
}
