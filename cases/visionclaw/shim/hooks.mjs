// The gateway's model client is gateway/src/cma.ts (`export const anthropic = new Anthropic()`), imported as
// "./cma.js" by provision.ts, turn.ts, connect.ts and health.ts. It resolves to cma_stub.mjs instead; every
// other module resolves as usual.
const STUB = new URL("./cma_stub.mjs", import.meta.url).href;

export async function resolve(specifier, context, nextResolve) {
  if (specifier === "./cma.js" && context.parentURL && context.parentURL.includes("/gateway/src/")) {
    return { url: STUB, format: "module", shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
