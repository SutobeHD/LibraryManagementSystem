// Dev-only logging utility.
//
// `log.debug` / `log.info` are silenced in production builds via Vite's
// `import.meta.env.DEV` guard, so verbose component traces stay out of the
// shipped bundle while still being available during `npm run dev`.
//
// `log.warn` and `log.error` are NEVER guarded — those signals matter in
// production too, and the existing `console.error / console.warn` call
// sites are intentionally preserved.
//
// Usage:
//   import { log } from "../utils/log";   // or "../../utils/log" — adjust depth
//   log.debug("waveform cache miss", { trackId });
//   log.info("Component mounted", { props });
//   log.warn("retrying after 500", { attempt });
//   log.error("API call failed", { endpoint, status });

const isDev = typeof import.meta !== "undefined" && import.meta.env && import.meta.env.DEV;

function noop() {}

export const log = {
  debug: isDev ? console.debug.bind(console) : noop,
  info: isDev ? console.info.bind(console) : noop,
  // warn/error are always on — they're production-relevant signals.
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

export default log;
