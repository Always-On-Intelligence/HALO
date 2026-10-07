// The gateway stamps notes, task-ledger entries and the cross-call briefing with Date.now(). In run mode the
// clock reads the scripted time of the call (HALO_FROZEN_NOW_MS), so these texts are the same in every arm
// and do not depend on when an arm happened to run. Timers (setTimeout) keep real time.
const frozen = Number(process.env.HALO_FROZEN_NOW_MS);
if (frozen) {
  const RealDate = Date;
  class ScriptedDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(frozen);
      else super(...args);
    }
    static now() {
      return frozen;
    }
  }
  globalThis.Date = ScriptedDate;
}
