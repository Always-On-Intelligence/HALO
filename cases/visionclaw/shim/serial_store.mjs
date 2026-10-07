// gateway/src/store.ts saves the whole store by writing `${path}.tmp` and renaming it over the store file. Two
// saves that overlap share that temp file, so the second rename fails with ENOENT; when the save was not awaited
// (server.ts:289 and 295 on the hang-up path) the rejection is unhandled and the process exits. Run mode
// serializes each write-then-rename on a `.json.tmp` path, so overlapping saves land one after the other.
// Gateway logic is unchanged; only the order of these file operations is fixed.
import { createRequire, syncBuiltinESMExports } from "node:module";

const require = createRequire(import.meta.url);
const fsp = require("node:fs/promises");
const realWriteFile = fsp.writeFile;
const realRename = fsp.rename;
const tails = new Map();    // temp path -> promise that settles when the current holder has renamed
const holders = new Map();  // temp path -> release function of the current holder

fsp.writeFile = async function writeFile(file, data, options) {
  if (typeof file !== "string" || !file.endsWith(".json.tmp")) return realWriteFile(file, data, options);
  const before = tails.get(file) ?? Promise.resolve();
  let release;
  const mine = new Promise((resolve) => (release = resolve));
  tails.set(file, before.then(() => mine));
  await before;
  holders.set(file, release);
  try {
    return await realWriteFile(file, data, options);
  } catch (err) {
    holders.delete(file);
    release();
    throw err;
  }
};

fsp.rename = async function rename(from, to) {
  try {
    return await realRename(from, to);
  } finally {
    const release = typeof from === "string" ? holders.get(from) : undefined;
    if (release) {
      holders.delete(from);
      release();
    }
  }
};

syncBuiltinESMExports();
