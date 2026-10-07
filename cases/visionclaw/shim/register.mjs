// Registered after tsx (node --import tsx --import ./shim/register.mjs ...). Hooks run last-in first-out,
// so this resolve hook sees the gateway's "./cma.js" import before tsx maps it to a .ts file.
import { register } from "node:module";

register("./hooks.mjs", import.meta.url);
