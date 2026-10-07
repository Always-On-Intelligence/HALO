// Stand-in for the Anthropic SDK client of gateway/src/cma.ts. It exposes the Managed Agents calls the gateway
// makes (environments, agents, vaults, sessions, session events) and forwards each one to the HALO adapter's
// bridge (HALO_BRIDGE_URL), which keeps the session state and runs the action agent's turns on the HALO backbone.
const BRIDGE = process.env.HALO_BRIDGE_URL;

async function call(op, args) {
  const res = await fetch(BRIDGE, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ op, args: args ?? {} }),
  });
  const body = await res.json();
  if (!res.ok || body.error) throw new Error(`bridge ${op}: ${body.error ?? res.status}`);
  return body.result;
}

// List endpoints are async iterables in the SDK (`for await (const x of client.list(...))`).
function pages(op, args) {
  return {
    async *[Symbol.asyncIterator]() {
      for (const item of await call(op, args)) yield item;
    },
  };
}

// sessions.events.stream: opened before the user turn is sent, then drained until the session goes idle.
// Events queued after the stream opened are yielded in order; the bridge holds each request until one exists.
async function stream(sessionId) {
  const { cursor } = await call("sessions.events.open", { session_id: sessionId });
  let next = cursor;
  return {
    async *[Symbol.asyncIterator]() {
      for (;;) {
        const { event, cursor: after } = await call("sessions.events.next", { session_id: sessionId, cursor: next });
        next = after;
        yield event;
      }
    },
  };
}

export const anthropic = {
  beta: {
    environments: { create: (args) => call("environments.create", args) },
    agents: {
      create: (args) => call("agents.create", args),
      retrieve: (id) => call("agents.retrieve", { id }),
      update: (id, args) => call("agents.update", { id, ...args }),
    },
    vaults: {
      create: (args) => call("vaults.create", args),
      credentials: {
        list: (vaultId) => pages("vaults.credentials.list", { vault_id: vaultId }),
        create: (vaultId, args) => call("vaults.credentials.create", { vault_id: vaultId, ...args }),
        delete: (credentialId, args) => call("vaults.credentials.delete", { id: credentialId, ...args }),
        mcpOAuthValidate: (credentialId, args) => call("vaults.credentials.validate", { id: credentialId, ...args }),
      },
    },
    sessions: {
      create: (args) => call("sessions.create", args),
      retrieve: (id) => call("sessions.retrieve", { id }),
      update: (id, args) => call("sessions.update", { id, ...args }),
      events: {
        send: (sessionId, args) => call("sessions.events.send", { session_id: sessionId, ...args }),
        list: (sessionId) => pages("sessions.events.list", { session_id: sessionId }),
        stream: (sessionId) => stream(sessionId),
      },
    },
  },
};
