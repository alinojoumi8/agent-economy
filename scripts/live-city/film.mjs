/**
 * The capture, made watchable.
 *   city-running.mp4  the whole session at 8x
 *   moment-*.jpg      the stills that carry the finding
 */
import { readFileSync, mkdirSync, copyFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

const DIR = process.argv[2];
const P = JSON.parse(readFileSync(join(DIR, "probe.json"), "utf8"));
const OUT = join(DIR, "film");
mkdirSync(OUT, { recursive: true });
const ff = (...a) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...a], { stdio: "inherit" });

const T0 = P.notes.find(n => /run\/start/.test(n.text)).t;
const shotAt = relS => {
  const want = T0 + relS * 1000;
  let best = 0;
  for (let i = 0; i < P.shots.length; i++) {
    if (Math.abs(P.shots[i] - want) < Math.abs(P.shots[best] - want)) best = i;
  }
  return best;
};
const still = i => join(DIR, "frames", `f${String(i).padStart(4, "0")}.jpg`);

ff("-framerate", "8", "-i", join(DIR, "frames", "f%04d.jpg"),
   "-vf", "scale=1280:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
   join(OUT, "city-running.mp4"));
console.log("city-running.mp4  (326 stills at 8 fps = 8x real time)");

const moments = [
  [-5, "00-paused-baseline", "before: world paused, city says Paused"],
  [60, "01-running-but-says-paused", "world is ticking hard; city still says Paused, still on tick 349"],
  [150, "02-stale", "city has noticed something is wrong: Stale"],
  [260, "03-reconnecting", "socket dead on a keepalive timeout: Reconnecting"],
  [347.5, "04-before-the-jump", "one second before the only new frame of truth"],
  [349.5, "05-after-the-jump", "tick 355 has landed; the day was cut off at 19.6% and everyone teleported"],
];
for (const [t, name, why] of moments) {
  const i = shotAt(t);
  copyFileSync(still(i), join(OUT, `moment-${name}.jpg`));
  console.log(`moment-${name}.jpg  t=${t}s (still ${i}) — ${why}`);
}

/* The teleport itself, as a four-up either side of the reset. */
const c = shotAt(348.6);
const list = join(OUT, "pair.txt");
const names = [c - 1, c, c + 1, c + 2].map(still);
/* The concat demuxer resolves paths against the list file, so absolute only. */
writeFileSync(list, names.map(f => `file '${resolve(f).replace(/\\/g, "/")}'`).join("\n"));
ff("-f", "concat", "-safe", "0", "-i", list, "-vf", "scale=620:-2,tile=2x2", "-frames:v", "1",
   join(OUT, "the-jump.jpg"));
console.log(`the-jump.jpg  (stills ${c - 1}..${c + 2} around the 330 px teleport)`);
