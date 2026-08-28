/**
 * Driftgram landing page.
 *
 * Four small things, no framework and no build step for the JS:
 *   1. point the hero button at the file the visitor actually needs
 *   2. the screenshot tabs
 *   3. the sync-loop diagram
 *   4. scroll reveals
 *
 * Everything degrades: with JS off the hero button still links to the Windows
 * installer, the first screenshot is already in the markup, the diagram sits
 * on its opening caption, and the reveal class is neutralised by CSS.
 */
(() => {
  "use strict";

  const REPO = "https://github.com/devwithfarshi/driftgram-sync-tool";
  const VERSION = "1.0.0";
  const DL = `${REPO}/releases/download/v${VERSION}`;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------------
     1. Platform-aware download button
     --------------------------------------------------------------------- */
  const BUILDS = {
    windows: { label: "Download for Windows", file: `Driftgram-${VERSION}-Setup.exe` },
    linux: { label: "Download for Linux", file: `Driftgram-${VERSION}-x86_64.AppImage` },
  };

  function detectPlatform() {
    // userAgentData where it exists, userAgent where it doesn't. Anything that
    // isn't recognisably Linux gets the Windows installer, which is both the
    // larger audience and the friendlier failure.
    const platform = (
      navigator.userAgentData?.platform ||
      navigator.platform ||
      navigator.userAgent ||
      ""
    ).toLowerCase();

    // Android reports "linux" but must not be offered an AppImage.
    if (/android|iphone|ipad|ipod/.test(navigator.userAgent.toLowerCase())) return null;
    if (platform.includes("linux") || platform.includes("x11")) return "linux";
    if (platform.includes("win")) return "windows";
    return null;
  }

  function setUpDownload() {
    const button = document.getElementById("primary-download");
    if (!button) return;

    const key = detectPlatform();
    if (!key) {
      // Mobile, macOS, or something unknown: don't pretend there's a build.
      button.textContent = "See all downloads";
      button.setAttribute("href", "#download");
      return;
    }

    const build = BUILDS[key];
    button.textContent = build.label;
    button.setAttribute("href", `${DL}/${build.file}`);
  }

  /* ---------------------------------------------------------------------
     2. Screenshot tabs
     --------------------------------------------------------------------- */
  function setUpTabs() {
    const list = document.getElementById("shot-tabs");
    const img = document.getElementById("shot-img");
    if (!list || !img) return;

    const tabs = Array.from(list.querySelectorAll('[role="tab"]'));

    const select = (tab) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.classList.toggle("tab-active", on);
        t.classList.toggle("text-muted", !on);
      });
      img.src = tab.dataset.src;
      img.alt = tab.dataset.alt || "";
    };

    list.addEventListener("click", (event) => {
      const tab = event.target.closest('[role="tab"]');
      if (tab) select(tab);
    });

    // Left/right arrows move between tabs, which is what a tablist owes a
    // keyboard user.
    list.addEventListener("keydown", (event) => {
      const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      const current = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
      const next = tabs[(current + step + tabs.length) % tabs.length];
      select(next);
      next.focus();
    });
  }

  /* ---------------------------------------------------------------------
     3. The sync loop
     --------------------------------------------------------------------- */

  // Beats, in the order they'd actually happen. Beat 2 is the one worth
  // showing: the echo of our own upload arriving back and being refused. That
  // refusal is the whole reason the tool doesn't loop.
  const BEATS = [
    {
      caption: "You save a file in a watched folder. It isn't in the manifest, so it goes up.",
      file: "invoice.pdf",
      from: "local",
      verdict: "new · upload",
      verdictColor: "#38B6F1",
      pass: true,
    },
    {
      caption:
        "Telegram hands that upload straight back as a new message. The manifest already has this message id, so it stops here — this is the loop that never starts.",
      file: "invoice.pdf",
      from: "remote",
      verdict: "already known · ignore",
      verdictColor: "#9AA7B6",
      pass: false,
    },
    {
      caption: "Your phone sends a file. Nothing on record matches it, so it comes down into the right folder.",
      file: "receipt.jpg",
      from: "remote",
      verdict: "not on record · download",
      verdictColor: "#38B6F1",
      pass: true,
    },
    {
      caption: "Both sides agree with the manifest. Nothing moves until content actually differs.",
      file: null,
      from: null,
      verdict: "up to date",
      verdictColor: "#3DBE6C",
      pass: null,
    },
  ];

  const X_LOCAL = 196;
  const X_GATE = 400;
  const X_REMOTE = 604;
  const Y = 110;

  function setUpLoop() {
    const svg = document.getElementById("loop-svg");
    if (!svg) return;

    const packet = document.getElementById("packet");
    const packetLabel = document.getElementById("packet-label");
    const verdict = document.getElementById("gate-verdict");
    const gateBox = document.getElementById("gate-box");
    const localDot = document.getElementById("node-local-dot");
    const remoteDot = document.getElementById("node-remote-dot");
    const caption = document.getElementById("loop-caption");
    const stepLabel = document.getElementById("loop-step");

    let index = 0;
    let raf = null;
    let timer = null;
    let running = false;

    const place = (x, opacity) => {
      packet.setAttribute("transform", `translate(${x} ${Y})`);
      packet.setAttribute("opacity", String(opacity));
    };

    const render = (beat, i) => {
      stepLabel.textContent = `step ${i + 1} of ${BEATS.length}`;
      caption.textContent = beat.caption;
      verdict.textContent = beat.verdict;
      verdict.setAttribute("fill", beat.verdictColor);
      gateBox.setAttribute("stroke", beat.pass === false ? "#9AA7B6" : "#38B6F1");

      const settled = beat.pass === null ? "#3DBE6C" : "#38B6F1";
      localDot.setAttribute("fill", beat.from === "local" ? settled : "#3DBE6C");
      remoteDot.setAttribute("fill", beat.from === "remote" ? settled : "#3DBE6C");

      if (beat.file) packetLabel.textContent = beat.file;
    };

    // Reduced motion: show each beat's end state on a timer, no travel.
    const staticBeat = () => {
      const beat = BEATS[index];
      render(beat, index);
      place(beat.from === "remote" ? X_GATE + 70 : X_GATE - 70, beat.file ? 1 : 0);
      index = (index + 1) % BEATS.length;
      timer = window.setTimeout(staticBeat, 4200);
    };

    const animateBeat = () => {
      const beat = BEATS[index];
      render(beat, index);

      if (!beat.file) {
        place(X_GATE, 0);
        timer = window.setTimeout(next, 2600);
        return;
      }

      const forward = beat.from === "local";
      const start = forward ? X_LOCAL : X_REMOTE;
      // A refused packet travels only as far as the gate and fades there.
      const end = beat.pass ? (forward ? X_REMOTE : X_LOCAL) : X_GATE;
      const duration = beat.pass ? 2100 : 1250;
      const t0 = performance.now();

      const frame = (now) => {
        const t = Math.min(1, (now - t0) / duration);
        // easeInOutCubic: leaves and arrives calmly rather than at constant speed.
        const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        const x = start + (end - start) * e;

        // Fade in off the node, and out again either on arrival or at the gate
        // when the manifest refuses it.
        let opacity = 1;
        if (t < 0.12) opacity = t / 0.12;
        else if (!beat.pass && t > 0.62) opacity = Math.max(0, (1 - t) / 0.38);
        else if (beat.pass && t > 0.9) opacity = Math.max(0, (1 - t) / 0.1);

        place(x, opacity);

        if (t < 1) raf = requestAnimationFrame(frame);
        else timer = window.setTimeout(next, beat.pass ? 900 : 1500);
      };

      raf = requestAnimationFrame(frame);
    };

    const next = () => {
      index = (index + 1) % BEATS.length;
      animateBeat();
    };

    const stop = () => {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      if (timer) clearTimeout(timer);
      raf = timer = null;
    };

    const start = () => {
      if (running) return;
      running = true;
      if (reduceMotion) staticBeat();
      else animateBeat();
    };

    // Only run while the diagram is actually on screen - an animation looping
    // in a scrolled-past section is wasted battery.
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(
        (entries) => entries.forEach((e) => (e.isIntersecting ? start() : stop())),
        { threshold: 0.25 }
      ).observe(svg);
    } else {
      start();
    }

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stop();
    });
  }

  /* ---------------------------------------------------------------------
     4. Scroll reveals
     --------------------------------------------------------------------- */
  function setUpReveals() {
    const items = document.querySelectorAll(".reveal");
    if (!items.length) return;

    if (reduceMotion || !("IntersectionObserver" in window)) {
      items.forEach((el) => el.classList.add("is-in"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry, i) => {
          if (!entry.isIntersecting) return;
          // A short stagger within one screenful reads as one movement
          // instead of several unrelated ones.
          window.setTimeout(() => entry.target.classList.add("is-in"), i * 70);
          obs.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );

    items.forEach((el) => observer.observe(el));
  }

  /* --------------------------------------------------------------------- */
  const init = () => {
    setUpDownload();
    setUpTabs();
    setUpLoop();
    setUpReveals();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
