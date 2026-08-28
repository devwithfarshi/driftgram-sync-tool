/**
 * Driftgram landing page.
 *
 * Seven small things, no framework and no build step for the JS:
 *   1. point the hero button at the file the visitor actually needs
 *   2. the header's star and fork counts
 *   3. the mobile menu
 *   4. which nav link is lit
 *   5. the screenshot tabs
 *   6. the sync-loop diagram
 *   7. the sideways-scroll affordance on the two over-wide panels
 *   8. scroll reveals
 *
 * Everything degrades: with JS off the hero button still links to the Windows
 * installer, the header is just the GitHub mark with no counters, the section
 * links are ordinary anchors in a menu that is simply always closed on a
 * phone, the first screenshot is already in the markup, the diagram sits on
 * its opening caption, and the reveal class is neutralised by CSS.
 */
(() => {
  "use strict";

  const SLUG = "devwithfarshi/driftgram-sync-tool";
  const REPO = `https://github.com/${SLUG}`;
  const VERSION = "1.0.0";
  const DL = `${REPO}/releases/download/v${VERSION}`;

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const reduceMotion = motionQuery.matches;

  /* ---------------------------------------------------------------------
     1. Platform-aware download button
     --------------------------------------------------------------------- */
  // One record per platform, driving both the hero button and the featured
  // panel in the download section. The panel ships the Windows copy in the
  // markup, so this only has to rewrite it when the visitor isn't on Windows.
  const BUILDS = {
    windows: {
      // heroLabel names the platform, because up in the hero there is no
      // other context; label sits under a heading that already said which
      // platform this is, so it can name the file instead.
      heroLabel: "Download for Windows",
      label: "Download for Windows",
      file: `Driftgram-${VERSION}-Setup.exe`,
      os: "Windows 10 / 11",
      size: "27 MB",
      icon: "windows",
      kind:
        "A per-user installer, so there is no administrator prompt and nothing " +
        "outside your own account is touched.",
      note:
        "Windows shows a SmartScreen warning the first time, because the " +
        "installer isn't code-signed. Choose More info → Run anyway.",
    },
    linux: {
      heroLabel: "Download for Linux",
      label: "Download the AppImage",
      file: `Driftgram-${VERSION}-x86_64.AppImage`,
      os: "Any Linux distribution",
      size: "69 MB",
      icon: "linux",
      kind:
        "A portable AppImage — one file, nothing to install, and it leaves no " +
        "trace outside your home directory. A .deb is below if you would rather " +
        "use apt.",
      note: `Make it executable before the first run: chmod +x Driftgram-${VERSION}-x86_64.AppImage`,
    },
  };

  // macOS, a phone, or something unrecognised. There is no packaged build to
  // offer, so the panel says so and points at the thing that does work rather
  // than handing over a file that won't run.
  const NO_BUILD = {
    label: "Set it up in the terminal",
    href: "#cli",
    os: "macOS and everything else",
    icon: "terminal",
    kind:
      "There is no packaged desktop app for this system yet — the app is built " +
      "and tested on Windows and Linux. The command-line version is the same " +
      "engine and runs anywhere Python does.",
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

  // Swaps which of the three platform glyphs in the featured panel is shown.
  function showIcon(name) {
    document.querySelectorAll("[data-dl-icon]").forEach((svg) => {
      svg.classList.toggle("hidden", svg.dataset.dlIcon !== name);
    });
  }

  const setText = (selector, value) => {
    const el = document.querySelector(selector);
    if (el) el.textContent = value;
  };

  function fillPanel(build) {
    const button = document.getElementById("dl-button");
    const label = document.getElementById("dl-button-label");
    const badge = document.getElementById("dl-badge");
    const note = document.getElementById("dl-note");

    showIcon(build.icon);
    setText("[data-dl-os]", build.os);
    setText("[data-dl-kind]", build.kind);

    if (button) button.setAttribute("href", build.href || `${DL}/${build.file}`);
    if (label) label.textContent = build.label;

    // No packaged build: there is no file name, size or platform caveat to
    // show, calling it "recommended" would be a stretch, a download arrow
    // would be a lie, and the ghost button would point at the same anchor the
    // primary one now does.
    const hasFile = Boolean(build.file);
    setText("[data-dl-file]", hasFile ? build.file : "");
    setText("[data-dl-size]", hasFile ? build.size : "");
    setText("[data-dl-sep]", hasFile ? " · " : "");
    if (badge) badge.hidden = !hasFile;
    if (note) note.hidden = !build.note;
    if (build.note) setText("[data-dl-note]", build.note);

    const icon = document.getElementById("dl-button-icon");
    const secondary = document.getElementById("dl-secondary");
    if (icon) icon.classList.toggle("hidden", !hasFile);
    if (secondary) secondary.hidden = !hasFile;
  }

  function setUpDownload() {
    const key = detectPlatform();
    const hero = document.getElementById("primary-download");

    if (!key) {
      // Mobile, macOS, or something unknown: don't pretend there's a build.
      if (hero) {
        hero.textContent = "See all downloads";
        hero.setAttribute("href", "#download");
      }
      fillPanel(NO_BUILD);
      return;
    }

    const build = BUILDS[key];
    if (hero) {
      hero.textContent = build.heroLabel;
      hero.setAttribute("href", `${DL}/${build.file}`);
    }
    // Windows is already what the markup says, so only Linux needs rewriting -
    // but running it either way keeps one code path instead of two.
    fillPanel(build);
  }

  /* ---------------------------------------------------------------------
     2. Header star / fork counts
     --------------------------------------------------------------------- */

  // The counters are additive: the header is a working repo link before this
  // runs and stays one if the request fails, so no loading or error state is
  // ever shown. GitHub's unauthenticated API allows 60 requests an hour per
  // IP, hence the cache - a visitor reading a few sections and coming back
  // later should cost one request, not one per page view.
  const STATS_KEY = "driftgram:gh-stats";
  const STATS_TTL = 60 * 60 * 1000;

  function compact(n) {
    if (n < 1000) return String(n);
    // 1200 -> 1.2k, 12000 -> 12k. One decimal only while it says something.
    const k = n / 1000;
    return `${k < 10 ? k.toFixed(1).replace(/\.0$/, "") : Math.round(k)}k`;
  }

  function showStats(stats) {
    const pairs = [
      ["gh-stars", stats.stars],
      ["gh-forks", stats.forks],
    ];
    pairs.forEach(([id, value]) => {
      if (typeof value !== "number") return;
      const el = document.getElementById(id);
      if (!el) return;
      el.querySelector(".gh-count").textContent = compact(value);
      // sm:flex, not flex - see the comment on the link in index.html.
      el.classList.add("sm:flex");
    });
  }

  function readCachedStats() {
    try {
      const raw = window.localStorage.getItem(STATS_KEY);
      if (!raw) return null;
      const cached = JSON.parse(raw);
      if (!cached || Date.now() - cached.at > STATS_TTL) return null;
      return cached;
    } catch {
      // Private mode, disabled storage, or something else wrote the key.
      return null;
    }
  }

  function setUpStats() {
    if (!document.getElementById("gh-link")) return;

    const cached = readCachedStats();
    if (cached) {
      showStats(cached);
      return;
    }

    fetch(`https://api.github.com/repos/${SLUG}`, {
      headers: { Accept: "application/vnd.github+json" },
    })
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((repo) => {
        const stats = {
          stars: repo.stargazers_count,
          forks: repo.forks_count,
          at: Date.now(),
        };
        showStats(stats);
        try {
          window.localStorage.setItem(STATS_KEY, JSON.stringify(stats));
        } catch {
          /* not being able to cache is not worth failing over */
        }
      })
      .catch(() => {
        /* Offline, rate-limited, or blocked: leave the plain repo link. */
      });
  }

  /* ---------------------------------------------------------------------
     3. Mobile menu
     --------------------------------------------------------------------- */

  // A disclosure, not a dialog: it pushes the page down rather than covering
  // it, so there's nothing to trap focus inside and no scroll to lock.
  function setUpMenu() {
    const button = document.getElementById("menu-button");
    const panel = document.getElementById("mobile-menu");
    const iconOpen = document.getElementById("menu-icon-open");
    const iconClose = document.getElementById("menu-icon-close");
    if (!button || !panel) return;

    const setOpen = (open) => {
      panel.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      button.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      iconOpen.classList.toggle("hidden", open);
      iconClose.classList.toggle("hidden", !open);
    };

    button.addEventListener("click", () => {
      setOpen(button.getAttribute("aria-expanded") !== "true");
    });

    // Following a link inside the menu should leave it behind.
    panel.addEventListener("click", (event) => {
      if (event.target.closest("a")) setOpen(false);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (button.getAttribute("aria-expanded") !== "true") return;
      setOpen(false);
      button.focus();
    });

    // Widening past the breakpoint reveals the real nav; an open panel left
    // behind would be a second copy of it.
    window.matchMedia("(min-width: 1024px)").addEventListener("change", (event) => {
      if (event.matches) setOpen(false);
    });
  }

  /* ---------------------------------------------------------------------
     4. Which nav link is lit
     --------------------------------------------------------------------- */

  // The page is one long scroll, so "where am I" has to come from what's on
  // screen rather than from the URL. The band is the upper third of the
  // viewport: a section counts as current once its top passes under the
  // sticky header, and stops when it leaves the top of the screen.
  function setUpScrollSpy() {
    const nav = document.getElementById("nav-links");
    if (!nav || !("IntersectionObserver" in window)) return;

    const links = new Map();
    nav.querySelectorAll("a[href^='#']").forEach((link) => {
      const section = document.getElementById(link.getAttribute("href").slice(1));
      if (section) links.set(section, link);
    });
    if (!links.size) return;

    const visible = new Set();
    const sections = Array.from(links.keys());

    const paint = () => {
      // First in document order, so overlapping sections resolve the same way
      // a reader would resolve them: the one they reached first.
      const current = sections.find((section) => visible.has(section));
      links.forEach((link, section) => {
        link.classList.toggle("is-current", section === current);
      });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) visible.add(entry.target);
          else visible.delete(entry.target);
        });
        paint();
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
    );

    sections.forEach((section) => observer.observe(section));
  }

  /* ---------------------------------------------------------------------
     5. Screenshot tabs
     --------------------------------------------------------------------- */

  // The ARIA tabs pattern: one stop in the page's tab order, arrows to move
  // between tabs once you're in. The panel keeps a fixed aspect ratio in CSS,
  // so swapping a 940x680 window for the 660x560 wizard doesn't shift the
  // page under whoever is reading it.
  function setUpTabs() {
    const list = document.getElementById("shot-tabs");
    const img = document.getElementById("shot-img");
    const panel = document.getElementById("shot-panel");
    if (!list || !img) return;

    const tabs = Array.from(list.querySelectorAll('[role="tab"]'));

    const select = (tab, { focus = false } = {}) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
      });
      img.src = tab.dataset.src;
      img.alt = tab.dataset.alt || "";
      if (panel && tab.id) panel.setAttribute("aria-labelledby", tab.id);
      if (focus) tab.focus();
    };

    list.addEventListener("click", (event) => {
      const tab = event.target.closest('[role="tab"]');
      if (tab) select(tab);
    });

    list.addEventListener("keydown", (event) => {
      const current = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
      let next = null;

      if (event.key === "ArrowRight") next = tabs[(current + 1) % tabs.length];
      else if (event.key === "ArrowLeft") next = tabs[(current - 1 + tabs.length) % tabs.length];
      else if (event.key === "Home") next = tabs[0];
      else if (event.key === "End") next = tabs[tabs.length - 1];

      if (!next) return;
      event.preventDefault();
      select(next, { focus: true });
    });
  }

  /* ---------------------------------------------------------------------
     6. The sync loop
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
      verdictColor: "#4ED084",
      pass: null,
    },
  ];

  // Geometry, in viewBox units, derived from the boxes drawn in index.html so
  // the two cannot drift apart. X_LOCAL and X_REMOTE are the facing edges of
  // the folder and Telegram nodes; the gate is the manifest, 192 wide about
  // its centre; the packet is the 74-wide chip.
  const X_LOCAL = 196;
  const X_GATE = 400;
  const X_REMOTE = 604;
  const GATE_HALF = 96;
  const PACKET_HALF = 37;
  const Y = 110;
  const SETTLED = "#4ED084";

  // Where a chip stops. Refused, it presses against the gate it bounced off;
  // accepted, it comes to rest beside the node it reached. Six units of air
  // against the gate and eight against a node, so nothing ever sits on a
  // border.
  const X_REFUSED_LEFT = X_GATE - GATE_HALF - 6 - PACKET_HALF;
  const X_REFUSED_RIGHT = X_GATE + GATE_HALF + 6 + PACKET_HALF;
  const X_ARRIVED_LOCAL = X_LOCAL + 8 + PACKET_HALF;
  const X_ARRIVED_REMOTE = X_REMOTE - 8 - PACKET_HALF;

  function setUpLoop() {
    const svg = document.getElementById("loop-svg");
    if (!svg) return;

    const figure = document.getElementById("loop-figure");
    const packet = document.getElementById("packet");
    const packetBox = document.getElementById("packet-box");
    const packetLabel = document.getElementById("packet-label");
    const verdict = document.getElementById("gate-verdict");
    const gateBox = document.getElementById("gate-box");
    const localDot = document.getElementById("node-local-dot");
    const remoteDot = document.getElementById("node-remote-dot");
    const caption = document.getElementById("loop-caption");
    const stepLabel = document.getElementById("loop-step");
    const toggle = document.getElementById("loop-toggle");
    const toggleLabel = document.getElementById("loop-toggle-label");
    const iconPlay = document.getElementById("loop-icon-play");
    const iconPause = document.getElementById("loop-icon-pause");
    const dotsBox = document.getElementById("loop-dots");

    let index = 0;
    let raf = null;
    let timer = null;
    let running = false;

    // Four independent reasons the animation may be still. It runs only when
    // all four agree, which is what keeps "paused by the reader" from being
    // undone by a scroll, and a hover from overriding an explicit pause.
    let userPaused = false;
    let onScreen = !("IntersectionObserver" in window);
    let hovered = false;
    let docVisible = !document.hidden;

    const shouldRun = () => !userPaused && onScreen && !hovered && docVisible;

    /* -- dots ---------------------------------------------------------- */
    const dots = BEATS.map((_, i) => {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className =
        "h-2.5 w-2.5 rounded-full border border-line bg-transparent transition-colors";
      dot.setAttribute("aria-label", `Show step ${i + 1} of ${BEATS.length}`);
      dot.addEventListener("click", () => {
        // Jumping is a deliberate act: hold there rather than sliding on to
        // the next beat a second later.
        index = i;
        setUserPaused(true);
        showStatic();
      });
      dotsBox?.appendChild(dot);
      return dot;
    });

    const paintDots = () => {
      dots.forEach((dot, i) => {
        const on = i === index;
        dot.style.backgroundColor = on ? "var(--color-cyan)" : "transparent";
        dot.style.borderColor = on ? "var(--color-cyan)" : "var(--color-line)";
        if (on) dot.setAttribute("aria-current", "true");
        else dot.removeAttribute("aria-current");
      });
    };

    /* -- drawing ------------------------------------------------------- */
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

      const active = beat.pass === null ? SETTLED : "#38B6F1";
      localDot.setAttribute("fill", beat.from === "local" ? active : SETTLED);
      remoteDot.setAttribute("fill", beat.from === "remote" ? active : SETTLED);

      // There are only ~34 units of slack between the gate and either node,
      // so "arrived at Telegram" and "refused at the gate" end up about 20
      // apart - too close to tell by position alone, and they run one after
      // the other. A refused chip goes grey instead, matching the grey the
      // gate stroke and the verdict already switch to.
      packetBox.setAttribute("fill", beat.pass === false ? "#9AA7B6" : "#38B6F1");

      if (beat.file) packetLabel.textContent = beat.file;
      paintDots();
    };

    // The resting frame for a beat: where the packet ended up once that beat
    // has played. Used for reduced motion and whenever the animation is
    // stopped, so a paused diagram shows a coherent state rather than a
    // packet frozen in mid-air.
    //
    // It has to be the outcome, not the origin. A downloaded file rests
    // beside the folder; a refused one rests against the manifest it bounced
    // off, dimmed. Showing it back where it started would contradict the
    // caption sitting underneath.
    const restFrame = (beat) => {
      if (!beat.file) return { x: X_GATE, opacity: 0 };
      if (beat.pass === false) {
        return {
          x: beat.from === "local" ? X_REFUSED_LEFT : X_REFUSED_RIGHT,
          opacity: 0.35,
        };
      }
      return {
        x: beat.from === "local" ? X_ARRIVED_REMOTE : X_ARRIVED_LOCAL,
        opacity: 1,
      };
    };

    const showStatic = () => {
      const beat = BEATS[index];
      render(beat, index);
      const rest = restFrame(beat);
      place(rest.x, rest.opacity);
    };

    /* -- playback ------------------------------------------------------ */
    const clear = () => {
      if (raf) cancelAnimationFrame(raf);
      if (timer) clearTimeout(timer);
      raf = timer = null;
    };

    const advance = () => {
      index = (index + 1) % BEATS.length;
      play();
    };

    // Reduced motion: step through the end states on a timer, no travel.
    const stepStatically = () => {
      showStatic();
      timer = window.setTimeout(() => {
        index = (index + 1) % BEATS.length;
        stepStatically();
      }, 4200);
    };

    const play = () => {
      const beat = BEATS[index];
      render(beat, index);

      if (!beat.file) {
        place(X_GATE, 0);
        timer = window.setTimeout(advance, 2600);
        return;
      }

      const forward = beat.from === "local";
      const start = forward ? X_LOCAL : X_REMOTE;
      // A refused packet travels only as far as the gate and fades against
      // it - stopping at the box's edge, not sliding into the middle of it.
      const end = beat.pass
        ? forward
          ? X_ARRIVED_REMOTE
          : X_ARRIVED_LOCAL
        : forward
          ? X_REFUSED_LEFT
          : X_REFUSED_RIGHT;
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
        else timer = window.setTimeout(advance, beat.pass ? 900 : 1500);
      };

      raf = requestAnimationFrame(frame);
    };

    // One place that reconciles the four reasons above with what is actually
    // scheduled, so every listener can just flip its own flag and call this.
    const sync = () => {
      const want = shouldRun();
      if (want === running) return;
      running = want;

      if (!want) {
        clear();
        showStatic();
        return;
      }
      if (reduceMotion) stepStatically();
      else play();
    };

    /* -- controls ------------------------------------------------------ */
    const setUserPaused = (paused) => {
      userPaused = paused;
      if (toggle) {
        const label = paused ? "Play the diagram" : "Pause the diagram";
        toggle.setAttribute("aria-label", label);
        if (toggleLabel) toggleLabel.textContent = label;
        iconPlay?.classList.toggle("hidden", !paused);
        iconPause?.classList.toggle("hidden", paused);
      }
      sync();
    };

    toggle?.addEventListener("click", () => setUserPaused(!userPaused));

    // Hovering or tabbing into the figure holds it still so the caption can
    // be read to the end. Leaving resumes, unless the reader paused it.
    if (figure) {
      const hold = (on) => {
        hovered = on;
        sync();
      };
      figure.addEventListener("pointerenter", () => hold(true));
      figure.addEventListener("pointerleave", () => hold(false));
      figure.addEventListener("focusin", () => hold(true));
      figure.addEventListener("focusout", (event) => {
        if (!figure.contains(event.relatedTarget)) hold(false);
      });
    }

    // Only run while the diagram is actually on screen - an animation looping
    // in a scrolled-past section is wasted battery.
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(
        (entries) =>
          entries.forEach((entry) => {
            onScreen = entry.isIntersecting;
            sync();
          }),
        { threshold: 0.25 }
      ).observe(svg);
    }

    document.addEventListener("visibilitychange", () => {
      docVisible = !document.hidden;
      sync();
    });

    setUserPaused(false);
    showStatic();
    sync();
  }

  /* ---------------------------------------------------------------------
     7. Sideways-scroll affordance
     --------------------------------------------------------------------- */

  // The diagram and the comparison table are both wider than a phone. The
  // markup ships the text hint visible and the fade off; this turns the fade
  // on while there is more to reach, and drops the hint on any screen wide
  // enough that there isn't.
  function setUpSwipeHints() {
    document.querySelectorAll("[data-swipe]").forEach((wrap) => {
      const scroller = wrap.querySelector("[data-swipe-scroller]");
      const note = wrap.parentElement?.querySelector("[data-swipe-note]");
      if (!scroller) return;

      const update = () => {
        const hidden = scroller.scrollWidth - scroller.clientWidth;
        // 8px of slack: sub-pixel layout shouldn't count as "there's more".
        wrap.dataset.more = String(hidden - scroller.scrollLeft > 8);
        if (note) note.hidden = hidden <= 8;
      };

      scroller.addEventListener("scroll", update, { passive: true });
      window.addEventListener("resize", update);
      update();
    });
  }

  /* ---------------------------------------------------------------------
     8. Scroll reveals
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
    setUpStats();
    setUpMenu();
    setUpScrollSpy();
    setUpTabs();
    setUpLoop();
    setUpSwipeHints();
    setUpReveals();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
